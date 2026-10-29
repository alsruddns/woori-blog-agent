"""Conservative read-only duplicate lookup for scheduled Blogger manuscripts."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any
from uuid import UUID

from . import blogger_service
from .google_http import GoogleFailure


def _possible_title_match(expected: str, actual: str) -> bool:
    left, right = " ".join(expected.casefold().split()), " ".join(actual.casefold().split())
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    return SequenceMatcher(a=left, b=right).ratio() >= 0.82


def find_remote_duplicate(blog_record_id: UUID, title: str, *, page_limit: int = 10) -> dict[str, Any]:
    """Return found/clear/unknown; a partial Blogger listing is never called clear."""
    token = ""
    scanned = 0
    try:
        for _ in range(page_limit):
            page = blogger_service.posts(blog_record_id, token, "live")
            items = page.get("items", [])
            scanned += len(items)
            for item in items:
                remote_title = str(item.get("title") or "")
                if _possible_title_match(title, remote_title):
                    return {"status": "found", "reason": "remote_live_title_match",
                            "post_id": str(item.get("id") or ""), "url": item.get("url"),
                            "scanned_posts": scanned}
            token = str(page.get("nextPageToken") or "")
            if not token:
                return {"status": "clear", "reason": "complete_live_post_listing_no_title_match",
                        "scanned_posts": scanned}
        return {"status": "unknown", "reason": "blogger_read_scan_limit_reached",
                "scanned_posts": scanned}
    except GoogleFailure as exc:
        return {"status": "unknown", "reason": exc.category, "http_status": exc.status,
                "scanned_posts": scanned}
