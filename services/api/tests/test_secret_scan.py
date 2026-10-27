from woori.secret_scan import database_url_metadata, redact_sensitive_text


def test_redacts_database_url_password_without_exposing_it() -> None:
    diagnostic = "psycopg failed: postgresql://eval_user:sensitive-value@127.0.0.1:5432/eval"

    safe = redact_sensitive_text(diagnostic)

    assert "sensitive-value" not in safe
    assert "postgresql://eval_user:[REDACTED]@127.0.0.1:5432/eval" in safe


def test_redacts_secret_assignment_variants() -> None:
    diagnostic = "password=hunter2 token:abc123 api_key=sk-example client_secret=oauth-secret"

    safe = redact_sensitive_text(diagnostic)

    assert "hunter2" not in safe
    assert "abc123" not in safe
    assert "sk-example" not in safe
    assert "oauth-secret" not in safe
    assert safe == (
        "password=[REDACTED] token:[REDACTED] api_key=[REDACTED] "
        "client_secret=[REDACTED]"
    )


def test_database_url_report_contains_identity_but_never_password() -> None:
    url = "postgresql://eval_owner:never-display-this@127.0.0.1:5432/evaluation"

    summary = database_url_metadata(url)

    assert summary == {
        "scheme": "postgresql",
        "username": "eval_owner",
        "host": "127.0.0.1",
        "port": 5432,
        "database": "evaluation",
        "credential_present": True,
    }
    assert "never-display-this" not in str(summary)


def test_redacts_quoted_json_secret_fields() -> None:
    safe = redact_sensitive_text('{"client_secret":"oauth-secret"}')

    assert "oauth-secret" not in safe
    assert safe == '{"client_secret":"[REDACTED]"}'
