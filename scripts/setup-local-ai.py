"""Opt-in project-only official CPU engine/model downloads with pinned hashes."""

import hashlib
import json
import shutil
from pathlib import Path
from zipfile import ZipFile

import httpx

root = Path(__file__).resolve().parents[1] / ".local"
root.mkdir(exist_ok=True)
if shutil.disk_usage(root).free < 20 * 1024**3:
    raise SystemExit("At least 20 GiB free required; no model download attempted")
with httpx.Client(timeout=120, follow_redirects=True, trust_env=False) as client:
    release = client.get(
        "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/b11889"
    ).json()
    asset = next(a for a in release["assets"] if a["name"] == "llama-b11889-bin-win-cpu-x64.zip")
    downloads = [(asset["browser_download_url"], asset["name"], asset["digest"].split(":")[1])]
    models = []
    for size, revision in [
        ("0.6B", "23749fefcc72300e3a2ad315e1317431b06b590a"),
        ("1.7B", "90862c4b9d2787eaed51d12237eafdfe7c5f6077"),
    ]:
        repo = f"Qwen/Qwen3-{size}-GGUF"
        filename = f"Qwen3-{size}-Q8_0.gguf"
        info = client.get(
            f"https://huggingface.co/api/models/{repo}/revision/{revision}",
            params={"blobs": "true"},
        )
        info.raise_for_status()
        item = next(s for s in info.json()["siblings"] if s["rfilename"] == filename)
        digest = item["lfs"]["sha256"]
        downloads.append(
            (f"https://huggingface.co/{repo}/resolve/{revision}/{filename}", filename, digest)
        )
        models.append(
            {
                "name": filename,
                "revision": revision,
                "sha256": digest,
                "license": "Apache-2.0",
                "repo": repo,
            }
        )
    for url, filename, digest in downloads:
        path = root / filename
        if not path.exists():
            print("Downloading official artifact:", filename, flush=True)
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with path.open("wb") as output:
                    for block in response.iter_bytes(1024 * 1024):
                        output.write(block)
        with path.open("rb") as downloaded:
            actual = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if actual != digest:
            raise SystemExit("Artifact hash mismatch; refusing execution")
        print("SHA256 verified:", filename, flush=True)
    engine = root / "llama-b11889"
    engine.mkdir(exist_ok=True)
    with ZipFile(root / asset["name"]) as archive:
        for item in archive.infolist():
            if not (engine / item.filename).resolve().is_relative_to(engine.resolve()):
                raise SystemExit("Unsafe archive member")
        archive.extractall(engine)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "engine": "llama.cpp b11889",
                "engine_license": "MIT",
                "engine_sha256": downloads[0][2],
                "models": models,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
print("Project-local CPU engine and pinned models ready; no PATH/service changes.")
from psycopg.types.json import Jsonb
from woori.db import connection

with connection() as conn:
    conn.execute(
        "INSERT INTO audit_events(event_type,payload) VALUES ('research.local.install_verified',%s)",
        (
            Jsonb(
                {
                    "engine": "llama.cpp b11889",
                    "artifact_hash": downloads[0][2],
                    "models": models,
                    "location": ".local",
                    "system_path_changed": False,
                }
            ),
        ),
    )
