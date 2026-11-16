import json
from pathlib import Path

import pytest
from woori.research_snapshot import read_snapshot, write_snapshot


@pytest.mark.parametrize("raw", [b"", b" ", b"{}", b"[]", b'{"bad":"\\ud800"}', b'{"bad":NaN}'])
def test_invalid_snapshot_does_not_create_output(tmp_path: Path, raw: bytes) -> None:
    source = tmp_path / "incoming.part"
    source.write_bytes(raw)
    target = tmp_path / "research" / "new.research.json"
    with pytest.raises((ValueError, UnicodeError)):
        write_snapshot(source, target)
    assert not target.exists()


def test_snapshot_atomic_exclusive_utf8_and_preserves_original(tmp_path: Path) -> None:
    source = tmp_path / "incoming.part"
    source.write_text(json.dumps({"topic": "K-POP 공연", "sources": ["official-notice"]}, ensure_ascii=False), encoding="utf-8")
    target = tmp_path / "research" / "new.research.json"
    digest = write_snapshot(source, target)
    assert len(digest) == 64
    assert read_snapshot(target)["topic"] == "K-POP 공연"
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        write_snapshot(source, target)
    assert target.read_bytes() == original
    assert not list(target.parent.glob("*.part"))
    empty = target.parent / "old-empty.research.json"
    empty.touch()
    with pytest.raises(ValueError, match="empty_research_snapshot"):
        read_snapshot(empty)
    assert empty.exists() and empty.stat().st_size == 0
