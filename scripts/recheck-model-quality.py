"""Append a rule-only recheck of retained model samples without mutating measurements."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb
from woori.ai import Draft
from woori.db import connection
from woori.grounding import inspect

VERSION = "p3.6-quality-gates-v2"
MODELS = (
    "Qwen3-1.7B-Q8_0.gguf",
    "Qwen3-4B-Q4_K_M.gguf",
    "Qwen3-8B-Q4_K_M.gguf",
)
ROOT = Path(__file__).resolve().parents[1]
material = json.loads((ROOT / "docs/audit/local-ai-material.json").read_text(encoding="utf-8"))
created: list[dict[str, Any]] = []

with connection() as conn:
    previous = conn.execute(
        """SELECT id,model,revision,language_code,status,sample,checks,metrics,error_category,material_hash
        FROM model_measurements WHERE model=ANY(%s)
        AND checks->>'protocol'='p3.6-evidence-led-v1' AND NOT (checks ? 'rule_recheck')
        ORDER BY created_at,model,language_code""",
        (list(MODELS),),
    ).fetchall()

for row in previous:
    if not row["sample"] or row["status"] != "succeeded":
        continue
    draft = Draft.model_validate(row["sample"])
    checks = dict(row["checks"])
    checks["grounding"] = inspect(
        draft,
        material["sources"],
        row["language_code"],
        datetime.now(UTC).date().isoformat(),
    )
    checks["rule_recheck"] = VERSION
    checks["source_measurement_id"] = str(row["id"])
    with connection() as conn:
        inserted = conn.execute(
            """INSERT INTO model_measurements
            (model,revision,language_code,material_hash,status,sample,checks,metrics,error_category)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (
                row["model"],
                row["revision"],
                row["language_code"],
                row["material_hash"],
                row["status"],
                Jsonb(row["sample"]),
                Jsonb(checks),
                Jsonb(row["metrics"]),
                row["error_category"],
            ),
        ).fetchone()
        assert inserted is not None
        conn.execute(
            """INSERT INTO audit_events(event_type,language_code,payload)
            VALUES ('research.model.quality.rechecked',%s,%s)""",
            (
                row["language_code"],
                Jsonb(
                    {
                        "source_measurement_id": str(row["id"]),
                        "measurement_id": str(inserted["id"]),
                        "model": row["model"],
                        "rule_version": VERSION,
                        "rule_pass": checks["grounding"]["rule_pass"],
                        "publish_ready": False,
                        "sample_changed": False,
                    }
                ),
            ),
        )
    created.append(
        {
            "model": row["model"],
            "language": row["language_code"],
            "status": row["status"],
            "rule_pass": checks["grounding"]["rule_pass"],
            "failed_rules": [
                key for key, passed in checks["grounding"]["rule_checks"].items() if not passed
            ],
        }
    )

for result in created:
    print(json.dumps(result, ensure_ascii=True))
