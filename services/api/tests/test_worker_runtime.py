import psycopg
import pytest
from woori.config import settings
from woori.publication_worker import safe_database_error_hint
from woori.worker import acquire_process_lock, release_process_lock


def test_safe_database_error_hint_reports_only_undefined_operator_signature() -> None:
    class Diagnostic:
        message_primary = "operator does not exist: timestamp with time zone < text"

    class DatabaseError(Exception):
        sqlstate = "42883"
        diag = Diagnostic()

    assert safe_database_error_hint(DatabaseError()) == (
        "undefined_operator:timestamp with time zone < text"
    )


def test_safe_database_error_hint_omits_unrecognized_message_and_non_undefined_errors() -> None:
    class Diagnostic:
        message_primary = "invalid input value: possible article title"

    class UndefinedError(Exception):
        sqlstate = "42883"
        diag = Diagnostic()

    class OtherError(Exception):
        sqlstate = "23514"
        diag = Diagnostic()

    assert safe_database_error_hint(UndefinedError()) == (
        "undefined_operator_or_function:invalid input value: possible article title"
    )
    assert safe_database_error_hint(OtherError()) is None


def test_safe_database_error_hint_redacts_quoted_values() -> None:
    class Diagnostic:
        message_primary = "operator does not exist: unusual 'private title' = text"

    class DatabaseError(Exception):
        sqlstate = "42883"
        diag = Diagnostic()

    hint = safe_database_error_hint(DatabaseError())
    assert hint is not None
    assert "private title" not in hint
    assert "<redacted>" in hint


def test_safe_database_error_hint_uses_exception_text_when_primary_is_missing() -> None:
    class Diagnostic:
        message_primary = None

    class DatabaseError(Exception):
        sqlstate = "42883"
        diag = Diagnostic()

    error = DatabaseError("operator does not exist: uuid = text")
    assert safe_database_error_hint(error) == "undefined_operator:uuid = text"


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
