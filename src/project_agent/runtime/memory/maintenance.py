from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from project_agent.errors import AgentError
from project_agent.runtime.memory.consolidator import MemoryConsolidator
from project_agent.runtime.memory.extractor import MemoryExtractor
from project_agent.runtime.memory.models import MemoryCandidate, check_text, check_topic
from project_agent.runtime.memory.store import FileMemoryStore
from project_agent.runtime.persistence import atomic_write, file_lock
from project_agent.runtime.session_store import FileSessionStore

LOGGER = logging.getLogger(__name__)


@dataclass
class MaintenanceResult:
    extracted: int = 0
    rejected: int = 0
    merged: int = 0
    deferred: int = 0
    archived: int = 0
    skipped: int = 0
    failed: int = 0


class MemoryMaintenance:
    def __init__(
        self,
        *,
        store: FileMemoryStore,
        sessions: FileSessionStore,
        extractor: MemoryExtractor,
        consolidator: MemoryConsolidator,
        idle_minutes: int = 30,
        max_sessions: int = 5,
        max_unused_days: int = 30,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.sessions = sessions
        self.extractor = extractor
        self.consolidator = consolidator
        self.idle_minutes = idle_minutes
        self.max_sessions = max_sessions
        self.max_unused_days = max_unused_days
        self.clock = clock
        self._stop = threading.Event()

    def start(self, *, exclude_session_id: str) -> threading.Thread:
        def work() -> None:
            try:
                self.refresh(exclude_session_id=exclude_session_id)
            except (AgentError, OSError, ValueError):
                LOGGER.warning("background memory maintenance failed", exc_info=True)

        thread = threading.Thread(target=work, name="memory-maintenance", daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()

    def refresh(self, *, force: bool = False, exclude_session_id: str = "") -> MaintenanceResult:
        self.store.ensure_initialized()
        report = MaintenanceResult()
        with file_lock(self.store.lock_path("maintenance")) as acquired:
            if not acquired:
                report.skipped += 1
                return report
            report.archived = self.store.archive_unused(
                max_unused_days=self.max_unused_days,
                now=self.clock(),
            )
            attempted = 0
            for session_id in self.sessions.session_ids():
                if self._stop.is_set() or attempted >= self.max_sessions:
                    break
                # Subagent prompts are generated instructions, not user preference evidence.
                if session_id == exclude_session_id or ".agent." in session_id:
                    continue
                try:
                    with file_lock(self.sessions.activity_path(session_id)) as available:
                        if not available:
                            report.skipped += 1
                            continue
                        snapshot = self.sessions.memory_snapshot(session_id)
                    revision = snapshot.revision
                    memory_state = self.store.read_state()
                    if (
                        not snapshot.generation_enabled
                        or memory_state["processed"].get(session_id) == revision
                        or (
                            not force
                            and self.clock() - snapshot.updated_at < self.idle_minutes * 60
                        )
                        or not any(m.role == "user" for m in snapshot.messages)
                        or not any(m.role == "assistant" and m.content for m in snapshot.messages)
                    ):
                        report.skipped += 1
                        continue
                    attempted += 1
                    batch_name = hashlib.sha256(session_id.encode()).hexdigest()
                    batch_path = self.store._resolve_inside(
                        self.store.memory_dir / "candidates" / f"{batch_name}.json"
                    )
                    batch = (
                        json.loads(batch_path.read_text(encoding="utf-8"))
                        if batch_path.exists()
                        else {}
                    )
                    if batch.get("revision") == revision:
                        candidates = tuple(
                            MemoryCandidate.from_dict(item) for item in batch["memories"]
                        )
                    else:
                        extraction = self.extractor.extract(
                            session_id=session_id,
                            messages=snapshot.messages,
                            topics=tuple(memory_state["topics"]),
                        )
                        candidates = extraction.candidates
                        report.extracted += len(candidates)
                        report.rejected += extraction.rejected
                        if extraction.rejected:
                            LOGGER.info(
                                "memory extraction for session %s rejected %d candidate(s): "
                                "evidence did not exactly match the supplied conversation",
                                session_id,
                                extraction.rejected,
                            )
                    # Write only sanitized, validated candidates; never duplicate raw transcripts.
                    with file_lock(self.store.lock_path(), blocking=True):
                        forgotten = self.store.read_state()["forgotten"]
                        candidates = tuple(c for c in candidates if c.topic not in forgotten)
                        atomic_write(
                            batch_path,
                            json.dumps(
                                {
                                    "session_id": session_id,
                                    "revision": revision,
                                    "memories": [c.to_dict() for c in candidates],
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                        )
                    if self._stop.is_set():
                        break
                    updates, expected, deferred = self.consolidator.prepare(candidates)
                    if self._stop.is_set():
                        break
                    # Models run outside locks. Recheck activity and revision before publishing.
                    with file_lock(self.sessions.activity_path(session_id)) as available:
                        if (
                            not available
                            or self.sessions.memory_snapshot(session_id).revision != revision
                        ):
                            report.skipped += 1
                            continue
                        self.store.commit(updates, expected=expected)
                        report.merged += len(updates)
                        report.deferred += len(deferred)
                        if not deferred:
                            self.store.mark_processed(session_id, revision)
                            batch_path.unlink(missing_ok=True)
                except (AgentError, OSError, ValueError, KeyError, TypeError):
                    report.failed += 1
                    LOGGER.warning(
                        "memory maintenance failed for session %s", session_id, exc_info=True
                    )
        return report

    def remember(
        self,
        *,
        topic: str,
        content: str,
        evidence: str,
        session_id: str,
        pinned: bool = False,
    ) -> None:
        self.store.ensure_initialized()
        candidate = MemoryCandidate(
            topic=check_topic(topic),
            content=check_text(content, limit=2000),
            evidence=check_text(evidence, limit=1000),
            source_session_id=session_id,
            created_at=self.clock(),
        )
        updates, expected, deferred = self.consolidator.prepare((candidate,))
        if deferred:
            raise AgentError("memory conflicts with existing evidence; clarify before saving")
        self.store.commit(updates, expected=expected, explicit=True)
        if pinned:
            self.store.set_pinned(topic, True)
