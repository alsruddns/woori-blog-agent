"""Opt-in synthetic E2E through the real Dashboard proxy and scheduled Worker."""

import sys
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx

if "--mock-demo" not in sys.argv:
    raise SystemExit("Pass --mock-demo to retain clearly marked synthetic internal drafts.")
base = "http://127.0.0.1:3100/api/research"
with httpx.Client(
    timeout=15, trust_env=False, headers={"Origin": "http://127.0.0.1:3100"}
) as client:

    def call(method: str, path: str, body: object | None = None) -> dict:
        r = client.request(method, base + path, json=body)
        if not r.is_success:
            raise SystemExit("E2E request failed: " + str(r.status_code))
        return r.json()

    state = call("GET", "/state")
    active = {p["id"] for p in state["profiles"] if p["active"]}
    targets = [s for s in state["settings"] if s["profile_id"] in active and s["enabled"]]
    if not targets or any(s["provider"] != "mock" for s in targets):
        raise SystemExit(
            "E2E demo requires all enabled active profiles to use Mock; settings not changed."
        )
    tag = uuid4().hex
    expiry = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    k = call(
        "POST",
        "/keywords",
        {
            "profile_id": targets[0]["profile_id"],
            "category_id": state["categories"][0]["id"],
            "keyword": "MOCK pipeline verification " + tag,
            "search_intent": "Synthetic test only",
            "collection_source": "P3 synthetic E2E fixture",
            "rationale": "Verify pipeline; no real-world claims or search metrics",
            "expires_at": expiry,
        },
    )
    call("PUT", "/keywords/" + k["id"], {"status": "selected"})
    s = call(
        "POST",
        "/sources",
        {
            "keyword_id": k["id"],
            "url": "https://example.com/mock-" + tag,
            "source_name": "Synthetic fixture, not an external factual source",
            "evidence": "Synthetic test marker " + tag + ". This is not a real-world claim.",
            "reliability_reason": "Controlled synthetic input for Mock pipeline verification only",
            "rights": "Original synthetic test string; no third-party content",
            "access_policy": "Manual fixture registration only; no external page retrieved",
            "valid_until": expiry,
            "is_primary": True,
        },
    )
    call(
        "POST",
        "/sources/" + s["id"] + "/reviews",
        {
            "approved": True,
            "reviewer": "Mock E2E fixture",
            "reason": "Synthetic input consistency checked; NOT real factual verification",
        },
    )
    job = call("POST", "/jobs", {"keyword_id": k["id"], "idempotency_key": "demo-" + tag})
    for _ in range(30):
        state = call("GET", "/state")
        current = next(j for j in state["jobs"] if j["id"] == job["id"])
        if current["status"] in ("succeeded", "failed"):
            break
        time.sleep(2)
    versions = [v for v in state["versions"] if v.get("run_id") == job["id"]]
    if current["status"] != "succeeded" or len(versions) != len(targets):
        raise SystemExit("E2E incomplete: " + str(current.get("error_type")))
    assert all(
        v["state"] == "mock_draft" and not v["result_metadata"]["quality"]["publish_ready"]
        for v in versions
    )
    print(
        "Mock E2E succeeded; run",
        job["id"],
        "drafts",
        len(versions),
        "languages",
        sorted(v["language"] for v in versions),
    )
    print(
        "Synthetic drafts retained; no Google or paid AI requests. Real language quality NOT validated."
    )
