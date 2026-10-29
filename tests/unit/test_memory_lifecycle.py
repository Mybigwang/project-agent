from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from project_agent.core.interfaces import Tool
from project_agent.core.types import Message, SessionState
from project_agent.errors import AgentError, SessionError
from project_agent.runtime.agent import AgentRuntime
from project_agent.runtime.memory.builder import MemoryContextBuilder
from project_agent.runtime.memory.consolidator import MemoryConsolidator
from project_agent.runtime.memory.extractor import MemoryExtractor
from project_agent.runtime.memory.maintenance import MemoryMaintenance
from project_agent.runtime.memory.models import TopicUpdate
from project_agent.runtime.memory.recall import ModelMemoryRecall
from project_agent.runtime.memory.store import FileMemoryStore
from project_agent.runtime.memory.tools import RememberTool
from project_agent.runtime.session_store import FileSessionStore

FACT = "Use UTC for date tests."
DOCUMENT = "# Testing\n\nDate tests require UTC.\n\n- Use UTC for date tests."
EXTRACT = {"memories": [{"topic": "testing", "content": FACT, "evidence": FACT}]}
MERGE = {"updates": [{"topic": "testing", "content": DOCUMENT}], "unchanged": [], "deferred": []}


class ScriptedModel:
    name = "scripted-memory"

    def __init__(self, *responses: object, hook: Callable[[], None] | None = None) -> None:
        self.responses = list(responses)
        self.calls: list[Sequence[Message]] = []
        self.hook = hook

    def complete(
        self, *, messages: Sequence[Message], tools: Sequence[Tool], stream_callback: object = None
    ) -> Message:
        assert tools == ()
        self.calls.append(messages)
        if self.hook is not None:
            self.hook()
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return Message(role="assistant", content=json.dumps(response))


def setup_pipeline(tmp_path: Path, model: ScriptedModel) -> MemoryMaintenance:
    sessions = FileSessionStore(tmp_path / "sessions")
    sessions.save(
        "s1",
        SessionState(
            messages=(
                Message(role="user", content=FACT),
                Message(role="assistant", content="Verified."),
            )
        ),
    )
    store = FileMemoryStore(memory_dir=tmp_path / "memory")
    return MemoryMaintenance(
        store=store,
        sessions=sessions,
        extractor=MemoryExtractor(model),
        consolidator=MemoryConsolidator(model, store),
        clock=lambda: time.time() + 3600,
    )


def builder(
    store: FileMemoryStore, model: ScriptedModel, *, budget: int = 12000
) -> MemoryContextBuilder:
    return MemoryContextBuilder(
        store=store,
        recall=ModelMemoryRecall(model_client=model),
        entrypoint_max_lines=200,
        entrypoint_max_bytes=25000,
        max_relevant_files=3,
        max_relevant_file_chars=3000,
        max_manifest_files=50,
        prompt_max_chars=budget,
    )


def test_session_extraction_merge_and_revision_deduplication(tmp_path: Path) -> None:
    model = ScriptedModel(EXTRACT, MERGE)
    pipeline = setup_pipeline(tmp_path, model)
    result = pipeline.refresh()
    assert (result.extracted, result.merged, result.failed) == (1, 1, 0)
    assert pipeline.store.topic_path("testing").read_text(encoding="utf-8") == DOCUMENT
    state = pipeline.store.read_state()
    assert state["topics"]["testing"]["sources"] == ["s1"]
    assert state["processed"]["s1"] == pipeline.sessions.memory_snapshot("s1").revision
    assert not list((pipeline.store.memory_dir / "candidates").glob("*.json"))
    assert pipeline.refresh(force=True).skipped == 1
    assert len(model.calls) == 2


def test_memory_extraction_does_not_deserialize_agent_execution_state(tmp_path: Path) -> None:
    pipeline = setup_pipeline(tmp_path, ScriptedModel(EXTRACT, MERGE))
    path = tmp_path / "sessions" / "s1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["agent_runs"] = [
        {
            "agent_id": "worker-1",
            "session_id": "s1.agent.worker-1",
            "name": "worker",
            "description": "Inspect files",
            "kind": "worker",
            "status": "completed",
            "result_summary": "Done",
            "error": None,
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    original = path.read_bytes()

    # Runtime restoration still requires a complete, valid execution state.
    with pytest.raises(SessionError, match="failed to load session"):
        pipeline.sessions.load("s1")
    result = pipeline.refresh()
    assert (result.extracted, result.merged, result.failed) == (1, 1, 0)
    assert path.read_bytes() == original
    assert pipeline.store.topic_path("testing").read_text(encoding="utf-8") == DOCUMENT


def test_empty_conversation_with_incomplete_agent_run_is_skipped(tmp_path: Path) -> None:
    model = ScriptedModel()
    pipeline = setup_pipeline(tmp_path, model)
    (tmp_path / "sessions" / "s1.json").write_text(
        json.dumps({"messages": [], "agent_runs": [{"agent_id": "worker-1"}]}),
        encoding="utf-8",
    )
    result = pipeline.refresh()
    assert (result.skipped, result.failed) == (1, 0)
    assert not model.calls


def test_active_and_recent_sessions_are_skipped_even_when_force_is_requested(
    tmp_path: Path,
) -> None:
    model = ScriptedModel()
    pipeline = setup_pipeline(tmp_path, model)
    pipeline.clock = time.time
    assert pipeline.refresh().skipped == 1
    with pipeline.sessions.activity("s1"):
        assert pipeline.refresh(force=True).skipped == 1
        with pytest.raises(SessionError, match="already active"), pipeline.sessions.activity("s1"):
            pass
    assert not model.calls


def test_empty_extraction_is_success_and_does_not_invoke_consolidation(tmp_path: Path) -> None:
    model = ScriptedModel({"memories": []})
    pipeline = setup_pipeline(tmp_path, model)
    assert pipeline.refresh().failed == 0
    assert "s1" in pipeline.store.read_state()["processed"]
    assert len(model.calls) == 1


def test_unmatched_evidence_is_rejected_without_losing_valid_candidates(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    unsupported = {"topic": "invented", "content": "Unsupported claim", "evidence": "not quoted"}
    model = ScriptedModel({"memories": [unsupported, *EXTRACT["memories"]]}, MERGE)
    pipeline = setup_pipeline(tmp_path, model)
    result = pipeline.refresh()
    assert (result.extracted, result.rejected, result.merged, result.failed) == (1, 1, 1, 0)
    assert pipeline.store.topic_path("testing").read_text(encoding="utf-8") == DOCUMENT
    assert not pipeline.store.topic_path("invented").exists()
    assert len(json.loads(model.calls[-1][-1].content)["candidates"]) == 1
    assert "memory maintenance failed" not in caplog.text


def test_all_unmatched_evidence_is_discarded_without_repeated_extraction(tmp_path: Path) -> None:
    model = ScriptedModel(
        {"memories": [{"topic": "testing", "content": FACT, "evidence": "invented proof"}]}
    )
    pipeline = setup_pipeline(tmp_path, model)
    result = pipeline.refresh()
    assert (result.extracted, result.rejected, result.failed) == (0, 1, 0)
    assert not pipeline.store.topic_path("testing").exists()
    assert "s1" in pipeline.store.read_state()["processed"]
    assert pipeline.refresh(force=True).skipped == 1
    assert len(model.calls) == 1


def test_evidence_must_exist_in_the_bounded_model_input() -> None:
    model = ScriptedModel(EXTRACT)
    result = MemoryExtractor(model).extract(
        session_id="s1",
        messages=(
            Message(role="user", content=FACT),
            Message(role="assistant", content="x" * 60000),
        ),
        topics=(),
    )
    assert FACT not in json.loads(model.calls[0][-1].content)["conversation"]
    assert result.candidates == ()
    assert result.rejected == 1


def test_failed_merge_reuses_persisted_candidates_on_retry(tmp_path: Path) -> None:
    model = ScriptedModel(EXTRACT, AgentError("offline"), MERGE)
    pipeline = setup_pipeline(tmp_path, model)
    assert pipeline.refresh().failed == 1
    assert "s1" not in pipeline.store.read_state()["processed"]
    assert len(list((pipeline.store.memory_dir / "candidates").glob("*.json"))) == 1
    result = pipeline.refresh()
    assert (result.extracted, result.merged, result.failed) == (0, 1, 0)
    assert len(model.calls) == 3


def test_uncertain_conflict_stays_pending(tmp_path: Path) -> None:
    model = ScriptedModel(EXTRACT, {"updates": [], "unchanged": [], "deferred": ["testing"]})
    pipeline = setup_pipeline(tmp_path, model)
    result = pipeline.refresh()
    assert result.deferred == 1
    assert not pipeline.store.topic_path("testing").exists()
    assert "s1" not in pipeline.store.read_state()["processed"]


@pytest.mark.parametrize(
    "response",
    [
        {"memories": [{"topic": "../escape", "content": FACT, "evidence": FACT}]},
        {"memories": [{"topic": "testing", "content": "api_key=topsecret", "evidence": FACT}]},
        {"memories": "wrong shape"},
    ],
)
def test_bad_extraction_does_not_write_or_mark_processed(tmp_path: Path, response: object) -> None:
    pipeline = setup_pipeline(tmp_path, ScriptedModel(response))
    assert pipeline.refresh().failed == 1
    assert not pipeline.store.read_state()["processed"]
    assert not list((pipeline.store.memory_dir / "candidates").glob("*.json"))


def test_changed_session_during_model_call_is_not_published(tmp_path: Path) -> None:
    model = ScriptedModel(EXTRACT, MERGE)
    pipeline = setup_pipeline(tmp_path, model)

    def change_session() -> None:
        model.hook = None
        pipeline.sessions.save(
            "s1",
            SessionState(
                messages=(
                    Message(role="user", content="Actually this was a temporary workaround."),
                    Message(role="assistant", content="Understood."),
                )
            ),
        )

    model.hook = change_session
    assert pipeline.refresh().skipped == 1
    assert not pipeline.store.topic_path("testing").exists()
    assert "s1" not in pipeline.store.read_state()["processed"]


def test_archive_keeps_body_removes_index_and_only_recovers_after_delivery(tmp_path: Path) -> None:
    pipeline = setup_pipeline(tmp_path, ScriptedModel(EXTRACT, MERGE))
    pipeline.refresh()
    store = pipeline.store
    future = time.time() + 31 * 86400
    assert store.archive_unused(max_unused_days=30, now=future) == 1
    assert store.topic_path("testing").exists()
    assert "testing" not in store.read_entrypoint(max_lines=200, max_bytes=25000)[0]
    assert store.scan_memory_files(max_files=50) == ()
    context = builder(store, ScriptedModel({"files": ["topics/testing.md"]})).build(
        user_input="UTC"
    )
    assert context.relevant_files[0].relative_path == "topics/testing.md"
    assert context.on_recalled is not None
    context.on_recalled((Message(role="user", content="UTC"),))
    assert store.read_state()["topics"]["testing"]["status"] == "archived"
    context.on_recalled((Message(role="system", content=context.prompt),))
    metadata = store.read_state()["topics"]["testing"]
    assert metadata["status"] == "active"
    assert metadata["last_recalled_at"] is not None
    assert "topics/testing.md" in store.read_entrypoint(max_lines=200, max_bytes=25000)[0]


def test_pin_protects_idle_topic_and_scan_does_not_refresh_usage(tmp_path: Path) -> None:
    pipeline = setup_pipeline(tmp_path, ScriptedModel(EXTRACT, MERGE))
    pipeline.refresh()
    pipeline.store.set_pinned("testing", True)
    assert pipeline.store.archive_unused(max_unused_days=30, now=time.time() + 100 * 86400) == 0
    pipeline.store.scan_memory_files(max_files=50)
    assert pipeline.store.read_state()["topics"]["testing"]["last_recalled_at"] is None


def test_forget_removes_pending_content_and_blocks_automatic_resurrection(tmp_path: Path) -> None:
    model = ScriptedModel(EXTRACT, AgentError("offline"))
    pipeline = setup_pipeline(tmp_path, model)
    pipeline.refresh()
    pipeline.store.forget("testing")
    for path in (pipeline.store.memory_dir / "candidates").glob("*.json"):
        assert FACT not in path.read_text(encoding="utf-8")
    assert pipeline.refresh().failed == 0
    assert not pipeline.store.topic_path("testing").exists()
    model.responses.append(MERGE)
    pipeline.remember(
        topic="testing", content=FACT, evidence=FACT, session_id="explicit", pinned=True
    )
    assert pipeline.store.topic_path("testing").exists()
    assert "testing" not in pipeline.store.read_state()["forgotten"]
    assert pipeline.store.read_state()["topics"]["testing"]["pinned"] is True


def test_concurrent_topic_update_is_not_overwritten(tmp_path: Path) -> None:
    pipeline = setup_pipeline(tmp_path, ScriptedModel())
    pipeline.store.ensure_initialized()
    pipeline.store.topic_path("testing").write_text("# Newer\nDo not replace.", encoding="utf-8")
    with pytest.raises(AgentError, match="changed during consolidation"):
        pipeline.store.commit(
            (TopicUpdate("testing", DOCUMENT, ("s1",)),), expected={"testing": ""}
        )
    assert "Newer" in pipeline.store.topic_path("testing").read_text(encoding="utf-8")


def test_prompt_budget_drops_topic_without_falsely_recording_recall(tmp_path: Path) -> None:
    pipeline = setup_pipeline(tmp_path, ScriptedModel(EXTRACT, MERGE))
    pipeline.refresh()
    context = builder(
        pipeline.store, ScriptedModel({"files": ["topics/testing.md"]}), budget=256
    ).build(user_input="UTC")
    assert len(context.prompt) <= 256
    assert context.relevant_files == ()
    assert context.on_recalled is not None
    context.on_recalled((Message(role="system", content=context.prompt),))
    assert pipeline.store.read_state()["topics"]["testing"]["last_recalled_at"] is None


def test_remember_tool_uses_same_consolidation_and_rejects_credentials(tmp_path: Path) -> None:
    pipeline = setup_pipeline(tmp_path, ScriptedModel(MERGE))
    tool = RememberTool(pipeline, "explicit")
    result = tool.run(
        workspace_root=tmp_path, arguments={"topic": "testing", "content": FACT, "evidence": FACT}
    )
    assert not result.is_error
    assert pipeline.store.topic_path("testing").exists()
    result = tool.run(
        workspace_root=tmp_path,
        arguments={
            "topic": "secrets",
            "content": "password=secret-value",
            "evidence": "user request",
        },
    )
    assert result.is_error
    assert not pipeline.store.topic_path("secrets").exists()


def test_opted_out_session_stays_excluded_after_generation_is_enabled(tmp_path: Path) -> None:
    pipeline = setup_pipeline(tmp_path, ScriptedModel())
    state = pipeline.sessions.load("s1")
    opted_out = FileSessionStore(tmp_path / "sessions", memory_generation_enabled=False)
    opted_out.save("s1", state)
    pipeline.sessions.save("s1", state)
    assert pipeline.refresh(force=True).skipped == 1
    assert not pipeline.sessions.memory_snapshot("s1").generation_enabled


def test_new_revision_is_extracted_and_existing_topic_is_passed_to_merge(tmp_path: Path) -> None:
    updated = "# Testing\n\nDate tests require UTC and a database."
    model = ScriptedModel(
        EXTRACT,
        MERGE,
        EXTRACT,
        {
            "updates": [{"topic": "testing", "content": updated}],
            "unchanged": [],
            "deferred": [],
        },
    )
    pipeline = setup_pipeline(tmp_path, model)
    pipeline.refresh()
    first_revision = pipeline.store.read_state()["processed"]["s1"]
    original = pipeline.sessions.load("s1")
    pipeline.sessions.save(
        "s1",
        SessionState(
            messages=(
                *original.messages,
                Message(role="user", content="Also start the database."),
                Message(role="assistant", content="Verified again."),
            )
        ),
    )
    assert pipeline.refresh().merged == 1
    assert pipeline.store.read_state()["processed"]["s1"] != first_revision
    assert DOCUMENT in json.loads(model.calls[-1][-1].content)["existing"].values()
    assert pipeline.store.topic_path("testing").read_text(encoding="utf-8") == updated


def test_invalid_merge_cannot_modify_unrelated_topic(tmp_path: Path) -> None:
    model = ScriptedModel(
        EXTRACT,
        {
            "updates": [{"topic": "unrelated", "content": "# Changed\nWrong topic"}],
            "unchanged": [],
            "deferred": [],
        },
    )
    pipeline = setup_pipeline(tmp_path, model)
    assert pipeline.refresh().failed == 1
    assert not pipeline.store.topic_path("unrelated").exists()
    assert not pipeline.store.read_state()["processed"]


def test_runtime_records_delivery_but_failed_model_request_does_not(tmp_path: Path) -> None:
    pipeline = setup_pipeline(tmp_path, ScriptedModel(EXTRACT, MERGE))
    pipeline.refresh()
    runtime = AgentRuntime()

    def run(model: ScriptedModel) -> None:
        runtime.run_turn(
            session_id="current",
            user_input="UTC",
            model_client=model,
            tools=(),
            session_store=pipeline.sessions,
            workspace_root=tmp_path,
            max_steps=2,
            memory_context_builder=builder(
                pipeline.store, ScriptedModel({"files": ["topics/testing.md"]})
            ),
        )

    with pytest.raises(AgentError, match="offline"):
        run(ScriptedModel(AgentError("offline")))
    assert pipeline.store.read_state()["topics"]["testing"]["last_recalled_at"] is None
    run(ScriptedModel({"answer": "Use UTC"}))
    assert pipeline.store.read_state()["topics"]["testing"]["last_recalled_at"] is not None
