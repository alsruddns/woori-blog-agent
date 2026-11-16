from copy import deepcopy

from woori.claim_evidence import assess_claim_evidence


def test_exact_source_proof_does_not_fabricate_semantic_or_rights_approval():
    item = {"id": "import", "sources": [{"source_id": "s", "url": "https://example.org"}],
            "claims": [{"claim_id": "c", "claim": "Rate is 3%", "source_ids": ["s"],
                        "evidence_excerpt": "Rate is 3%"}]}
    proof = {"s": {"source_id": "s", "import_id": "import", "source_url": "https://example.org",
                   "http_status": 200, "source_body_sha256": "a" * 64,
                   "verified_claim_evidence": ["Rate is 3%"]}}
    original = deepcopy(item)
    result = assess_claim_evidence(item, proof)
    assert result["source_span_confirmed_count"] == 1
    assert result["verified_count"] == 0 and not result["publish_eligible"]
    assert item == original
    item["claims"][0]["claim"] = "Rate is 9%"
    assert assess_claim_evidence(item, proof)["source_span_confirmed_count"] == 0
    proof["s"]["source_url"] = "https://other.example"
    assert assess_claim_evidence(item, proof)["source_span_confirmed_count"] == 0
