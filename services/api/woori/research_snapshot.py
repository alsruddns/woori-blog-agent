"""Immutable local research artifacts; no Import or publication side effects."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_snapshot(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if not raw.strip():
        raise ValueError("empty_research_snapshot")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError("research_snapshot_must_be_nonempty_object")
    # Reject lone surrogates before opening any output file.
    json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return data


def write_snapshot(source: Path, destination: Path) -> str:
    data = read_snapshot(source)
    raw = (json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-volume atomic exclusive publication: never overwrite prior evidence.
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return hashlib.sha256(raw).hexdigest()
