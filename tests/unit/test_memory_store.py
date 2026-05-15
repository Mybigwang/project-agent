from pathlib import Path

import pytest

from project_agent.errors import ConfigurationError
from project_agent.runtime.memory.store import FileMemoryStore


def test_memory_store_initializes_directory_and_entrypoint(tmp_path: Path) -> None:
    store = FileMemoryStore(memory_dir=tmp_path / "memory")

    store.ensure_initialized()

    assert store.memory_dir.is_dir()
    assert (store.memory_dir / "MEMORY.md").read_text(encoding="utf-8") == ""


def test_memory_store_reads_and_truncates_entrypoint_by_lines(tmp_path: Path) -> None:
    store = FileMemoryStore(memory_dir=tmp_path)
    (tmp_path / "MEMORY.md").write_text("one\ntwo\nthree", encoding="utf-8")

    content, truncated = store.read_entrypoint(max_lines=2, max_bytes=100)

    assert content == "one\ntwo"
    assert truncated is True


def test_memory_store_reads_and_truncates_entrypoint_by_bytes(tmp_path: Path) -> None:
    store = FileMemoryStore(memory_dir=tmp_path)
    (tmp_path / "MEMORY.md").write_text("abcdef", encoding="utf-8")

    content, truncated = store.read_entrypoint(max_lines=10, max_bytes=3)

    assert content == "abc"
    assert truncated is True


def test_memory_store_scans_markdown_topics(tmp_path: Path) -> None:
    store = FileMemoryStore(memory_dir=tmp_path)
    (tmp_path / "MEMORY.md").write_text("- [Auth](auth.md)", encoding="utf-8")
    (tmp_path / "auth.md").write_text("# Auth\n\nUse OAuth for login.", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")

    files = store.scan_memory_files(max_files=10)

    assert len(files) == 1
    assert files[0].relative_path == "auth.md"
    assert files[0].title == "Auth"
    assert files[0].description == "Use OAuth for login."


def test_memory_store_limits_scanned_files(tmp_path: Path) -> None:
    store = FileMemoryStore(memory_dir=tmp_path)
    (tmp_path / "a.md").write_text("# A", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B", encoding="utf-8")

    files = store.scan_memory_files(max_files=1)

    assert len(files) == 1


def test_memory_store_reads_memory_file_with_char_limit(tmp_path: Path) -> None:
    store = FileMemoryStore(memory_dir=tmp_path)
    path = tmp_path / "topic.md"
    path.write_text("abcdef", encoding="utf-8")
    file = store.scan_memory_files(max_files=10)[0]

    content, truncated = store.read_memory_file(file, max_chars=3)

    assert content == "abc"
    assert truncated is True


def test_memory_store_treats_invalid_utf8_entrypoint_as_empty(tmp_path: Path) -> None:
    store = FileMemoryStore(memory_dir=tmp_path)
    (tmp_path / "MEMORY.md").write_bytes(b"\xff\xfe")

    content, truncated = store.read_entrypoint(max_lines=10, max_bytes=100)

    assert content == ""
    assert truncated is False


def test_memory_store_skips_invalid_utf8_topic_files(tmp_path: Path) -> None:
    store = FileMemoryStore(memory_dir=tmp_path)
    (tmp_path / "broken.md").write_bytes(b"\xff\xfe")
    (tmp_path / "valid.md").write_text("# Valid\n\nReadable", encoding="utf-8")

    files = store.scan_memory_files(max_files=10)

    assert tuple(file.relative_path for file in files) == ("valid.md",)


def test_memory_store_treats_invalid_utf8_memory_file_as_empty(tmp_path: Path) -> None:
    store = FileMemoryStore(memory_dir=tmp_path)
    path = tmp_path / "broken.md"
    path.write_text("# Broken", encoding="utf-8")
    file = store.scan_memory_files(max_files=10)[0]
    path.write_bytes(b"\xff\xfe")

    content, truncated = store.read_memory_file(file, max_chars=100)

    assert content == ""
    assert truncated is False


def test_memory_store_rejects_paths_outside_memory_dir(tmp_path: Path) -> None:
    store = FileMemoryStore(memory_dir=tmp_path / "memory")

    with pytest.raises(ConfigurationError, match="within memory_dir"):
        store._resolve_inside(tmp_path / "outside.md")
