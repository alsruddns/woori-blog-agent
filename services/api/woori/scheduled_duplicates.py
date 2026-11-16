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


def find_remote_duplicate(blog_record_id: UUID, title: str, *, page_limit: int = 10,
                          include_drafts: bool = False, exclude_post_id: str = "") -> dict[str, Any]:
    """A clear result requires complete listing of every requested remote state."""
    scanned = 0
    try:
        for remote_state in (["live", "draft"] if include_drafts else ["live"]):
            token = ""
            for _ in range(page_limit):
                page = blogger_service.posts(blog_record_id, token, remote_state)
                items = page.get("items", [])
                scanned += len(items)
                for item in items:
                    if exclude_post_id and str(item.get("id")) == exclude_post_id:
                        continue
                    if _possible_title_match(title, str(item.get("title") or "")):
                        return {"status": "found", "reason": "remote_"+remote_state+"_title_match",
                                "post_id": str(item.get("id") or ""), "url": item.get("url"), "scanned_posts": scanned}
                token = str(page.get("nextPageToken") or "")
                if not token:
                    break
            else:
                return {"status": "unknown", "reason": "blogger_read_scan_limit_reached", "scanned_posts": scanned}
        return {"status": "clear", "reason": "complete_live_post_listing_no_title_match" if not include_drafts else "complete_live_and_draft_listing_no_title_match", "scanned_posts": scanned}
    except GoogleFailure as exc:
        return {"status": "unknown", "reason": exc.category, "http_status": exc.status, "scanned_posts": scanned}
