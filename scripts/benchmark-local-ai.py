"""Actual CPU inference on identical public-domain material and all active DB languages."""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from psycopg.types.json import Jsonb
from woori.ai import EngineFailure, LocalProvider
from woori.db import connection
from woori.grounding import inspect
from woori.local_inference import runtime

sys.stdout.reconfigure(encoding="utf-8")
folder = Path(__file__).resolve().parents[1] / ".local"
info = runtime()
manifest = json.loads((folder / "manifest.json").read_text())
revision = next(m["revision"] for m in manifest["models"] if m["name"] == info["model"])
# Actual official release text, captured separately from the allowlisted collector.
material = json.loads((folder.parent / "docs/audit/local-ai-material.json").read_text(encoding="utf-8"))
digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
with connection() as conn:
    languages = conn.execute("SELECT code FROM languages WHERE active ORDER BY code").fetchall()
for row in languages:
    context = {
        **material,
        "language_code": row["code"],
        "target_country": "",
        "as_of": datetime.now(UTC).date().isoformat(),
        "instructions": "Write 4 informative sections with ## headings and useful summary in requested language. Test longer article structure, but never add facts not in evidence. Preserve names, dates, citations. Do not fabricate statistics.",
    }
    policy = {
        "language_verified": True,
        "engine": "llamacpp",
        "model": info["model"],
        "timeout_seconds": 180,
        "threads": 4,
        "max_tokens": 1600,
    }
    metrics = {}
    sample = None
    checks = {
        "protocol": "v2-explicit-language",
        "real_inference": True,
        "human_review_required": True,
        "publish_ready": False,
    }
    error = None
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
