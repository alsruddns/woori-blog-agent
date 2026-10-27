"""Opt-in project-only engine/model downloads with pinned hashes."""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from zipfile import ZipFile

from dotenv import load_dotenv

root_path = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root_path / "services" / "api"))
parser = argparse.ArgumentParser()
parser.add_argument("--with-vulkan", action="store_true", help="Install a separate project-local Vulkan engine")
parser.add_argument("--with-qwen3-4b-instruct-2507", action="store_true", help="Install the pinned evaluation-only comparison model")
parser.add_argument("--evaluation-only", action="store_true", help="Use the isolated evaluation DB for install audit events")
args = parser.parse_args()
if args.evaluation_only and not load_dotenv(root_path / ".env.evaluation", override=True):
    raise SystemExit("Evaluation database settings are required; no artifact request was made")
from woori.external_policy import client as external_client

root = root_path / ".local"
root.mkdir(exist_ok=True)
if shutil.disk_usage(root).free < 20 * 1024**3:
    raise SystemExit("At least 20 GiB free required; no model download attempted")
with external_client("artifact_setup", "artifact_download", timeout=120, follow_redirects=True) as client:
    release = client.get(
        "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/b11889"
    ).json()
    asset = next(a for a in release["assets"] if a["name"] == "llama-b11889-bin-win-cpu-x64.zip")
    downloads = [(asset["browser_download_url"], asset["name"], asset["digest"].split(":")[1])]
    vulkan_asset = None
    if args.with_vulkan:
        vulkan_asset = next(
            a for a in release["assets"] if a["name"] == "llama-b11889-bin-win-vulkan-x64.zip"
        )
        downloads.append(
            (vulkan_asset["browser_download_url"], vulkan_asset["name"], vulkan_asset["digest"].split(":")[1])
        )
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
    for size, revision, filename, digest, bytes_on_disk in [
        (
            "4B",
            "bc640142c66e1fdd12af0bd68f40445458f3869b",
            "Qwen3-4B-Q4_K_M.gguf",
            "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5",
            2497280256,
        ),
        (
            "8B",
            "7c41481f57cb95916b40956ab2f0b139b296d974",
            "Qwen3-8B-Q4_K_M.gguf",
            "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785",
            5027783488,
        ),
    ]:
        repo = f"Qwen/Qwen3-{size}-GGUF"
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
                "quantization": "Q4_K_M",
                "size_bytes": bytes_on_disk,
            }
        )
    if args.with_qwen3_4b_instruct_2507:
        revision = "ae44f08e1392f39c0e474af10c3ff8355c8b6688"
        repo = "bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF"
        filename = "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
        digest = "2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e"
        size_bytes = 2497280736
        info = client.get(
            f"https://huggingface.co/api/models/{repo}/revision/{revision}",
            params={"blobs": "true"},
        )
        info.raise_for_status()
        metadata = next(s for s in info.json()["siblings"] if s["rfilename"] == filename)
        if metadata.get("lfs", {}).get("sha256") != digest or metadata.get("size") != size_bytes:
            raise SystemExit("Pinned comparison-model metadata changed; no model was installed")
        downloads.append(
            (f"https://huggingface.co/{repo}/resolve/{revision}/{filename}", filename, digest)
        )
        models.append(
            {
                "name": filename,
                "revision": revision,
                "sha256": digest,
                "license": "Apache-2.0 (upstream Qwen weights; derivative quantization)",
                "repo": repo,
                "quantization": "Q4_K_M",
                "size_bytes": size_bytes,
                "evaluation_only": True,
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
    if not (engine / "llama-server.exe").is_file():
        engine.mkdir(exist_ok=True)
        with ZipFile(root / asset["name"]) as archive:
            for item in archive.infolist():
                if not (engine / item.filename).resolve().is_relative_to(engine.resolve()):
                    raise SystemExit("Unsafe archive member")
            archive.extractall(engine)
    if vulkan_asset:
        vulkan_engine = root / "llama-b11889-vulkan"
        if not (vulkan_engine / "llama-server.exe").is_file():
            vulkan_engine.mkdir(exist_ok=True)
            with ZipFile(root / vulkan_asset["name"]) as archive:
                for item in archive.infolist():
                    if not (vulkan_engine / item.filename).resolve().is_relative_to(vulkan_engine.resolve()):
                        raise SystemExit("Unsafe Vulkan archive member")
                archive.extractall(vulkan_engine)
        (root / "vulkan-manifest.json").write_text(
            json.dumps(
                {
                    "engine": "llama.cpp b11889 Vulkan",
                    "license": "MIT",
                    "archive": vulkan_asset["name"],
                    "sha256": next(d[2] for d in downloads if d[1] == vulkan_asset["name"]),
                    "gpu_layers_default": 20,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
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
if vulkan_asset:
    print("Separate project-local Vulkan engine installed with pinned SHA-256.")
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
                    "vulkan_engine_hash": next(
                        (d[2] for d in downloads if "vulkan" in d[1]), None
                    ),
                    "models": models,
                    "location": ".local",
                    "system_path_changed": False,
                }
            ),
        ),
    )
