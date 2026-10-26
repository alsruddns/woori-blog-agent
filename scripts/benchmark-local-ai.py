"""Actual CPU inference on identical public-domain material and all active DB languages."""

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from psycopg.types.json import Jsonb
from woori.ai import EngineFailure, LocalProvider
from woori.db import connection
from woori.grounding import extract_facts, inspect
from woori.local_inference import auth_headers, runtime

sys.stdout.reconfigure(encoding="utf-8")
parser = argparse.ArgumentParser()
parser.add_argument("--language", action="append", help="Evaluate only this active language; repeatable")
args = parser.parse_args()
folder = Path(__file__).resolve().parents[1] / ".local"
info = runtime()
manifest = json.loads((folder / "manifest.json").read_text())
revision = next(m["revision"] for m in manifest["models"] if m["name"] == info["model"])
# Large local models may still be loading when the start script returns. Do not
# misclassify readiness as a language/model failure or bias the first language.
ready_by = time.monotonic() + 300
with httpx.Client(timeout=3, trust_env=False, follow_redirects=False, headers=auth_headers()) as client:
    while True:
        try:
            if client.get("http://127.0.0.1:11435/health").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        if time.monotonic() >= ready_by:
            raise SystemExit("Local model did not become ready within 300 seconds")
        time.sleep(2)
# Actual official release text, captured separately from the allowlisted collector.
material = json.loads((folder.parent / "docs/audit/local-ai-material.json").read_text(encoding="utf-8"))
instructions = "P3.6 evidence-led evaluation: write four informative sections in the requested language, preserve evidence-backed names/numbers/dates, cite every factual paragraph as [source:ID], and add no facts, URL, quotation, or experience absent from evidence."
model_material = {
    "keyword": material["keyword"],
    "sources": [
        {key: source[key] for key in ("id", "url", "evidence", "published_at") if key in source}
        for source in material["sources"]
    ],
}
digest = hashlib.sha256(
    json.dumps(
        {"material": model_material, "instructions": instructions, "protocol": "p3.6-evidence-led-v1"},
        sort_keys=True,
    ).encode()
).hexdigest()
with connection() as conn:
    languages = conn.execute("SELECT code FROM languages WHERE active ORDER BY code").fetchall()
if args.language:
    requested = set(args.language)
    active = {row["code"] for row in languages}
    if not requested.issubset(active):
        raise SystemExit("Requested benchmark language is not active")
    languages = [row for row in languages if row["code"] in requested]
for row in languages:
    context = {
        **material,
        "language_code": row["code"],
        "target_country": "",
        "as_of": datetime.now(UTC).date().isoformat(),
        "instructions": instructions,
        "verified_facts": extract_facts(material["sources"]),
    }
    policy = {
        "language_verified": True,
        "engine": "llamacpp",
        "model": info["model"],
        "timeout_seconds": 180,
        "threads": 4,
        "max_tokens": 1200,
    }
    metrics = {}
    sample = None
    checks = {
        "protocol": "p3.6-evidence-led-v1",
        "material_hash": digest,
        "instructions_hash": hashlib.sha256(instructions.encode()).hexdigest(),
        "real_inference": True,
        "human_review_required": True,
        "publish_ready": False,
    }
    error = None
    started = time.monotonic()
    try:
        draft = LocalProvider().generate(context, policy)
        sample = draft.model_dump()
        metrics = draft._metrics
        checks["grounding"] = inspect(draft, material["sources"], row["code"], context["as_of"])
        checks.update(
            json_schema_valid=True,
            sections=draft.body.count("##"),
            body_characters=len(draft.body),
            source_ids_valid=set(draft.source_ids).issubset({s["id"] for s in material["sources"]}),
        )
        status = "succeeded"
    except EngineFailure as exc:
        error, status = exc.category, "failed"
        metrics = {"wall_seconds": round(time.monotonic() - started, 3)}
    with connection() as conn:
        conn.execute(
            """INSERT INTO model_measurements(model,revision,language_code,material_hash,status,sample,checks,metrics,error_category)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                info["model"],
                revision,
                row["code"],
                digest,
                status,
                Jsonb(sample),
                Jsonb(checks),
                Jsonb(metrics),
                error,
            ),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,language_code,payload) VALUES ('research.model.measured',%s,%s)",
            (
                row["code"],
                Jsonb(
                    {
                        "model": info["model"],
                        "status": status,
                        "error_category": error,
                        "material_hash": digest,
                        "metrics": metrics,
                    }
                ),
            ),
        )
    print(info["model"], row["code"], status, error or "", json.dumps(metrics), flush=True)
