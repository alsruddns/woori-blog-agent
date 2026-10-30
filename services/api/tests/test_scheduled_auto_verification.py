from __future__ import annotations

from woori.scheduled_auto_verification import evaluate_scheduled_evidence, excerpt_supported


def test_abbreviated_evidence_requires_every_fragment_in_source_order() -> None:
    spans = ['Voting against the action were Cook and Hammack, who preferred to raise the rate by 1/4 percentage point.']
    assert excerpt_supported('Voting against ... were Cook and Hammack, who preferred to raise ... by 1/4 percentage point.', spans)
    assert not excerpt_supported('Voting against ... were Cook and Hammack, who preferred to lower ... by 1/4 percentage point.', spans)
    assert not excerpt_supported('by 1/4 percentage point ... Voting against the action', spans)
    assert not excerpt_supported('Voting against ... by 1/2 percentage point.', spans)


def test_retained_version_manifest_scopes_sanitizer_before_evidence_evaluation() -> None:
    from hashlib import sha256

    from woori.publication_worker import _scheduled_eligibility

    imported, proofs = _case()
    imported.update(language_code='en',event_group_id='',import_hash='c'*64)
    imported['claims'].append({'claim_id':'unsupported', 'claim':'Unverified claim',
        'source_ids':['source-1'],'verification_status':'unverified'})
    body = 'According to the agency, the reported figure was 12.5 percent. [source:source-1]\n\nThe reported figure is attributed to the agency. [source:source-1]'

    class Result:
        def __init__(self, row=None, rows=None): self.row,self.rows=row,rows
        def fetchone(self): return self.row
        def fetchall(self): return self.rows

    class Connection:
        def execute(self, query, params=None):
            if 'external_content_import_assessments' in query:
                assert params == ('import-1', 'version')
                return Result({'safe_html':'<p>Verified</p>','seo_checks':[]})
            if 'live_document_verified' in query:
                return Result(rows=[{'payload':proofs['source-1']}])
            if 'SELECT body FROM content_versions' in query: return Result({'body':body})
            if 'sanitization_revision_created' in query:
                assert params[0] == 'version'
                assert params[1] == sha256(body.encode()).hexdigest()
                return Result({'payload':{'retained_claim_ids':['claim-1']}})
            if 'scheduled_origin_recorded' in query:
                return Result({'payload':{'target_blog_id':'12345','target_language_code':'en'}})
            return Result()

    result = _scheduled_eligibility(Connection(), imported, {'id':'version','content_version_id':'content'},
        {'id':'blog','blog_id':'12345','language_code':'en','active':True,'connection_verified_at':True,'oauth_status':'connected'})
    assert result['reasons'] == [], result
    assert result['sanitizer']['substantive_blocks_remaining'] == 2


def test_missing_capture_is_not_reported_as_a_disproved_claim() -> None:
    imported, _ = _case()
    result = evaluate_scheduled_evidence(imported, version_sha256='a'*64,
        source_proofs={}, human_review=None, scheduled_publish_first=True)
    assert 'claim_source_verification_unavailable' in result['reasons']
    assert 'claim_span_not_found_in_live_source_evidence' not in result['reasons']
    assert result['status'] == 'held'


def _case() -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    imported: dict[str, object] = {
        "id": "import-1",
        "generation_method": "chatgpt_scheduled_export",
        "sources": [{
            "source_id": "source-1",
            "url": "https://official.example.gov/release/1",
            "organization": "Official Agency",
            "rights_status": "open_license",
        }],
        "claims": [{
            "claim_id": "claim-1",
            "claim": "The agency reported 12.5 percent.",
            "source_ids": ["source-1"],
            "evidence_excerpt": "The agency reported 12.5 percent.",
            "verification_status": "source_span_verified",
        }],
    }
    proofs = {
        "source-1": {
            "source_id": "source-1",
            "import_id": "import-1",
            "source_url": "https://official.example.gov/release/1",
            "http_status": 200,
            "source_body_sha256": "a" * 64,
            "verified_claim_evidence": ["The agency reported 12.5 percent."],
            "reuse_terms_verified": True,
            "reuse_terms_status": "allowed",
            "reuse_terms_url": "https://official.example.gov/reuse",
            "reuse_terms_sha256": "b" * 64,
            "reuse_policy_id": "example-official-reuse",
            "reuse_policy_version": "1",
            "reuse_policy_expires_at": "2099-01-01T00:00:00Z",
        }
    }
    return imported, proofs


def test_source_and_numeric_checks_do_not_substitute_for_semantic_review() -> None:
    imported, proofs = _case()
    result = evaluate_scheduled_evidence(
        imported, version_sha256="c" * 64, source_proofs=proofs, human_review=None,
    )
    assert result["status"] == "held"
    assert "semantic_claim_review_required" in result["reasons"]
    assert result["checks"]["human_claim_review_present"] is False
    assert result["checks"]["human_rights_review_present"] is False
    assert result["claim_ids"] == ["claim-1"]
    assert result["source_evidence_sha256"]["source-1"]["source_body_sha256"] == "a" * 64


def test_human_review_allows_a_supported_paraphrase_without_literal_sentence_match() -> None:
    imported, proofs = _case()
    imported["claims"][0]["claim"] = "The reported rate reached 12.5 percent."
    result = evaluate_scheduled_evidence(
        imported, version_sha256="c" * 64, source_proofs=proofs,
        human_review={"claims_checked": True, "rights_reviewed": True},
    )
    assert result["status"] == "passed"
    assert result["checks"]["claim_source_spans"] is True
    assert result["checks"]["human_claim_review_present"] is True


def test_scheduled_machine_evidence_holds_unknown_rights() -> None:
    imported, proofs = _case()
    imported["sources"][0]["rights_status"] = "quotation_review_required"
    result = evaluate_scheduled_evidence(
        imported, version_sha256="c" * 64, source_proofs=proofs, human_review=None,
    )
    assert result["status"] == "held"
    assert "source_rights_not_machine_verified" in result["reasons"]


def test_scheduled_machine_evidence_holds_expired_reuse_policy() -> None:
    imported, proofs = _case()
    proofs["source-1"]["reuse_policy_expires_at"] = "2000-01-01T00:00:00Z"
    result = evaluate_scheduled_evidence(
        imported, version_sha256="c" * 64, source_proofs=proofs, human_review=None,
    )
    assert result["status"] == "held"
    assert "source_rights_not_machine_verified" in result["reasons"]


def test_scheduled_evidence_holds_unsupported_number_or_hash() -> None:
    imported, proofs = _case()
    imported["claims"][0]["claim"] = "The agency reported 13 percent."
    result = evaluate_scheduled_evidence(
        imported, version_sha256="not-a-sha", source_proofs=proofs, human_review=None,
    )
    assert result["status"] == "held"
    assert "scheduled_version_hash_invalid" in result["reasons"]
    assert "claim_contains_unsupported_number_or_unit" in result["reasons"]


def test_currency_units_percent_and_year_month_are_compared_semantically() -> None:
    imported, proofs = _case()
    imported["claims"][0]["claim"] = "2026년 9월 공공부문 차입은 18억 파운드와 7.7%로 보고됐다."
    imported["claims"][0]["evidence_excerpt"] = "£1.8 billion in September 2026; 7.7%"
    proofs["source-1"]["verified_claim_evidence"] = ["£1.8 billion in September 2026; 7.7%"]
    result = evaluate_scheduled_evidence(
        imported, version_sha256="c" * 64, source_proofs=proofs,
        human_review={"claims_checked": True, "rights_reviewed": True},
    )
    assert result["status"] == "passed"
    assert "claim_contains_unsupported_number_or_unit" not in result["reasons"]


def test_currency_unit_or_reference_month_mismatch_is_held() -> None:
    imported, proofs = _case()
    imported["claims"][0]["claim"] = "2026년 8월 차입은 19억 파운드였다."
    imported["claims"][0]["evidence_excerpt"] = "£1.8 billion in September 2026"
    proofs["source-1"]["verified_claim_evidence"] = ["£1.8 billion in September 2026"]
    result = evaluate_scheduled_evidence(
        imported, version_sha256="c" * 64, source_proofs=proofs,
        human_review={"claims_checked": True, "rights_reviewed": True},
    )
    assert result["status"] == "held"
    assert "claim_contains_unsupported_number_or_unit" in result["reasons"]


def test_korean_fiscal_month_range_matches_english_source_period() -> None:
    imported, proofs = _case()
    imported["claims"][0]["claim"] = "2026년 4~9월 순차입은 같은 기간 기준 열 번째로 높았다."
    imported["claims"][0]["evidence_excerpt"] = (
        "Borrowing in the FY to September 2026 was the 10th highest April-to-September figure."
    )
    proofs["source-1"]["verified_claim_evidence"] = [imported["claims"][0]["evidence_excerpt"]]
    result = evaluate_scheduled_evidence(
        imported, version_sha256="c" * 64, source_proofs=proofs,
        human_review={"claims_checked": True, "rights_reviewed": True},
    )
    assert result["status"] == "passed"


def test_bare_korean_month_range_and_relative_year_match_source_phrases() -> None:
    from woori.scheduled_auto_verification import _quantity_facts

    assert ("year_month_range", "04-09") in _quantity_facts("2026년 4~9월 기간")
    assert ("year_month_range", "04-09") in _quantity_facts("4~9월 기간")
    assert ("year_month", "2026-09") in _quantity_facts("2026년 4월부터 9월까지")
    assert ("year_month_range", "04-09") in _quantity_facts("April-to-September figure")
    assert ("calendar_month", "09") in _quantity_facts("September")
    assert ("year_offset", "1") in _quantity_facts("1년 전보다 낮았다")
    assert ("year_offset", "1") in _quantity_facts("lower than a year earlier")


def test_corroborated_claim_requires_distinct_organizations() -> None:
    imported, proofs = _case()
    imported["claims"][0]["verification_status"] = "corroborated"
    imported["claims"][0]["source_ids"] = ["source-1", "source-1"]
    result = evaluate_scheduled_evidence(
        imported, version_sha256="c" * 64, source_proofs=proofs, human_review=None,
    )
    assert result["status"] == "held"
    assert "independent_corroboration_missing" in result["reasons"]
