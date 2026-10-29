"""Deterministic, non-submitting Blogger package for future publication workflows."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_publication_package(
    *,
    title: str,
    post_html: str,
    labels: list[str],
    language_code: str,
    target_blog: dict[str, Any] | None,
    content_version_id: str | None,
    editorial_revision_id: str | None,
    revision_number: int | None,
    body_sha256: str,
    rendered_sha256: str,
    seo_metadata: dict[str, Any],
    validation: list[dict[str, str]],
    renderer_version: str,
    design_system_version: str,
) -> dict[str, Any]:
    """Assemble a preview artifact; this function has no network or database access."""
    target = None
    blockers: list[str] = []
    if target_blog is None:
        blockers.append("target_blog_not_selected_or_registered")
    else:
        target = {
            "blog_record_id": str(target_blog["id"]),
            "blog_id": target_blog.get("blog_id"),
            "url": str(target_blog["url"]),
            "display_name": str(target_blog["display_name"]),
            "language_code": str(target_blog["language_code"]),
            "active": bool(target_blog["active"]),
            "mapping_verified_at": (
                target_blog["connection_verified_at"].isoformat()
                if hasattr(target_blog.get("connection_verified_at"), "isoformat")
                else target_blog.get("connection_verified_at")
            ),
        }
        if not target["active"]:
            blockers.append("target_blog_inactive")
        if target["language_code"] != language_code:
            blockers.append("target_blog_language_mismatch")
        if not target["blog_id"] or not target["mapping_verified_at"]:
            blockers.append("target_blog_mapping_not_verified")
        # A stored mapping check is not a fresh Blogger API access test.
        blockers.append("live_blogger_access_not_rechecked")
    if not content_version_id:
        blockers.append("content_version_identity_missing")

    # Only documented Blogger Posts fields are placed in the future request body.
    request_body = {"title": title, "content": post_html, "labels": labels}
    package_without_generated_at: dict[str, Any] = {
        "package_version": "1.0.0",
        "target_blog": target,
        "request": {
            "method": "posts.insert",
            "query": {"isDraft": True},
            "body": request_body,
        },
        "editorial_version": {
            "content_version_id": content_version_id,
            "editorial_revision_id": editorial_revision_id,
            "revision_number": revision_number,
            "body_sha256": body_sha256,
            "rendered_sha256": rendered_sha256,
        },
        "idempotency_key": _stable_hash({
            "blog_record_id": target.get("blog_record_id") if target else None,
            "content_version_id": content_version_id,
            "rendered_sha256": rendered_sha256,
        }),
        "language_code": language_code,
        "labels": labels,
        "seo": {
            "title": seo_metadata.get("seo_title"),
            "title_candidates": seo_metadata.get("seo_title_candidates", []),
            "search_description": seo_metadata.get("search_description"),
            "search_description_api_supported": False,
            "search_description_manual_entry_required": bool(seo_metadata.get("search_description")),
            "search_intent": seo_metadata.get("search_intent"),
            "primary_keyword": seo_metadata.get("primary_keyword"),
            "related_terms": seo_metadata.get("related_terms", []),
            "core_question": seo_metadata.get("core_question"),
            "core_answer": seo_metadata.get("core_answer"),
            "target_region": seo_metadata.get("target_region"),
            "category": seo_metadata.get("category"),
            "author": seo_metadata.get("author"),
            "fact_verified_at": seo_metadata.get("fact_verified_at"),
            "editorial_status": seo_metadata.get("editorial_status"),
            "custom_permalink": None,
            "theme_level_review_required": True,
            "manual_tasks": [
                "Blogger editor search description",
                "custom permalink if required",
                "review theme-level canonical, robots, Open Graph and structured data",
            ],
        },
        "theme_compatibility": {
            "status": "live_theme_not_inspected",
            "required_review": [
                "post-body CSS selector conflicts",
                "mobile theme behavior",
                "font and content width inheritance",
                "canonical, robots, Open Graph and structured data duplication",
            ],
        },
        "sources": (
            [{key: value for key, value in source.items() if key != "official_status"}
             for source in seo_metadata["sources"]]
            if seo_metadata.get("sources") else
            [{**source, "official_status": "unverified"}
             for source in seo_metadata.get("official_sources", [])]
        ),
        "renderer_version": renderer_version,
        "design_system_version": design_system_version,
        "validation": validation,
        "editorial_approval": "not_evaluated_by_package_builder",
        "publish_ready": False,
        "submission_performed": False,
        "blockers": blockers,
    }
    artifact_hash = _stable_hash(package_without_generated_at)
    return {
        **package_without_generated_at,
        "generated_at": datetime.now(UTC).isoformat(),
        "package_sha256": artifact_hash,
    }
