from __future__ import annotations

import re
from pathlib import Path

from project_agent.core.types import RelevantFileExcerpt
from project_agent.runtime.workspace import relative_workspace_path

SEARCH_ROOTS = ("src", "tests")
ROOT_FILES = ("README.md", "CLAUDE.md", "AGENTS.md", "pyproject.toml")
TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
MAX_CANDIDATE_FILES = 200
MAX_FILE_SCAN_CHARS = 65_536


class RelevantFileCollector:
    def __init__(self, *, max_relevant_files: int, max_relevant_file_chars: int) -> None:
        self._max_relevant_files = max_relevant_files
        self._max_relevant_file_chars = max_relevant_file_chars

    def collect(
        self,
        *,
        workspace_root: Path,
        user_input: str,
        recent_user_messages: tuple[str, ...],
    ) -> tuple[RelevantFileExcerpt, ...]:
        root = workspace_root.resolve()
        tokens = _extract_tokens((user_input, *recent_user_messages))
        if not tokens:
            return ()

        matches: tuple[_FileMatch, ...] = ()
        for path in self._candidate_files(root):
            match = self._match_file(root=root, path=path, tokens=tokens)
            if match is not None:
                matches = matches + (match,)

        ordered = sorted(
            matches, key=lambda match: (_path_priority(match.path), -match.score, match.path)
        )[: self._max_relevant_files]
        return tuple(match.excerpt for match in ordered)

    def _candidate_files(self, root: Path) -> tuple[Path, ...]:
        files: tuple[Path, ...] = ()
        for root_name in SEARCH_ROOTS:
            search_root = root / root_name
            if search_root.exists():
                for path in search_root.rglob("*.py"):
                    if len(files) >= MAX_CANDIDATE_FILES:
                        return _sort_paths(root=root, paths=files)
                    if path.is_file() and _is_within_workspace(root=root, path=path):
                        files = files + (path,)
        for file_name in ROOT_FILES:
            file_path = root / file_name
            if file_path.is_file() and _is_within_workspace(root=root, path=file_path):
                files = files + (file_path,)
        return _sort_paths(root=root, paths=files)

    def _match_file(self, *, root: Path, path: Path, tokens: frozenset[str]) -> _FileMatch | None:
        relative_path = relative_workspace_path(workspace_root=root, target_path=path)
        path_text = relative_path.lower()
        path_hits = tuple(token for token in tokens if token in path_text)

        try:
            scanned = _read_scan_text(path)
        except UnicodeDecodeError:
            return None
        except OSError:
            return None
        scan_truncated = len(scanned) > MAX_FILE_SCAN_CHARS
        content = scanned[:MAX_FILE_SCAN_CHARS]

        content_text = content.lower()
        content_hits = tuple(token for token in tokens if token in content_text)
        if not path_hits and not content_hits:
            return None

        reasons: tuple[str, ...] = ()
        if path_hits:
            reasons = reasons + (f"path token: {path_hits[0]}",)
        if content_hits:
            reasons = reasons + (f"content token: {content_hits[0]}",)

        truncated = scan_truncated or len(content) > self._max_relevant_file_chars
        excerpt = RelevantFileExcerpt(
            path=relative_path,
            reason="; ".join(reasons),
            excerpt=content[: self._max_relevant_file_chars],
            truncated=truncated,
        )
        return _FileMatch(
            path=relative_path, score=(len(path_hits) * 2) + len(content_hits), excerpt=excerpt
        )


class _FileMatch:
    def __init__(self, *, path: str, score: int, excerpt: RelevantFileExcerpt) -> None:
        self.path = path
        self.score = score
        self.excerpt = excerpt


def _extract_tokens(texts: tuple[str, ...]) -> frozenset[str]:
    tokens: set[str] = set()
    for text in texts:
        for token in TOKEN_PATTERN.findall(text):
            tokens.add(token.lower())
            for part in _split_identifier(token):
                normalized_part = part.lower()
                if len(normalized_part) >= 3:
                    tokens.add(normalized_part)
    return frozenset(tokens)


def _split_identifier(token: str) -> tuple[str, ...]:
    parts: tuple[str, ...] = ()
    for snake_part in token.split("_"):
        parts = parts + tuple(part for part in re.split(r"(?=[A-Z])", snake_part) if part)
    return parts


def _sort_paths(*, root: Path, paths: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(
        sorted(
            paths,
            key=lambda path: relative_workspace_path(workspace_root=root, target_path=path),
        )
    )


def _is_within_workspace(*, root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _read_scan_text(path: Path) -> str:
    with path.open(encoding="utf-8") as file:
        return file.read(MAX_FILE_SCAN_CHARS + 1)


def _path_priority(path: str) -> int:
    if path.startswith("src/"):
        return 0
    if path.startswith("tests/"):
        return 1
    return 2
