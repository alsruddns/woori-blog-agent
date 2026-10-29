import psycopg
import pytest
from woori.config import settings
from woori.worker import acquire_process_lock, release_process_lock


def test_research_worker_session_lock_blocks_duplicate_process_and_releases() -> None:
    # Verify the isolated test identity before taking a session lock. No row is written.
    with psycopg.connect(settings().database_url) as conn:
        identity = conn.execute(
            "SELECT current_database(),current_user,inet_server_addr()::text"
        ).fetchone()
        assert identity and identity[0] == "woori_blog_agent_test"
        assert identity[1] == "woori_test_app"
        assert identity[2].split("/", maxsplit=1)[0] in {"127.0.0.1", "::1"}

    first = acquire_process_lock("research_worker")
    try:
        with pytest.raises(SystemExit, match="another_worker_holds_singleton_lock"):
            acquire_process_lock("research_worker")
    finally:
        release_process_lock(first, "research_worker")

    second = acquire_process_lock("research_worker")
    release_process_lock(second, "research_worker")


def test_publication_worker_session_lock_blocks_duplicate_process_and_releases() -> None:
    with psycopg.connect(settings().database_url) as conn:
        identity = conn.execute(
            "SELECT current_database(),current_user,inet_server_addr()::text"
        ).fetchone()
        assert identity and identity[0] == "woori_blog_agent_test"
        assert identity[1] == "woori_test_app"
        assert identity[2].split("/", maxsplit=1)[0] in {"127.0.0.1", "::1"}

    first = acquire_process_lock("publication_worker")
    try:
        with pytest.raises(SystemExit, match="another_worker_holds_singleton_lock"):
            acquire_process_lock("publication_worker")
    finally:
        release_process_lock(first, "publication_worker")

    second = acquire_process_lock("publication_worker")
    release_process_lock(second, "publication_worker")
