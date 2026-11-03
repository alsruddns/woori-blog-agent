from datetime import UTC, datetime, timedelta

import pytest
from woori.blogger_writes import interval_deadline


@pytest.mark.parametrize(('age','wait'),[
    (None,0),(30,870),(600,300),(899,1),(900,0),
])
def test_deadline_uses_global_15_minimum(age,wait):
    now=datetime(2026,10,30,7,tzinfo=UTC)
    assert interval_deadline(now-timedelta(seconds=age) if age is not None else None, now, 15)==now+timedelta(seconds=wait)


def test_global_interval_cannot_fall_back_to_ten_minutes_after_restart():
    now = datetime(2026, 11, 3, 0, 0, tzinfo=UTC)
    last_request = now - timedelta(minutes=10)
    # A restarted Worker reads the durable minimum; this is the same pure
    # deadline calculation used after every request and across all Blogger IDs.
    assert interval_deadline(last_request, now, 15) == now + timedelta(minutes=5)
    with pytest.raises(ValueError, match="at_least_15_minutes"):
        interval_deadline(last_request, now, 14)


@pytest.mark.parametrize("blog_id", ["blog-en", "blog-ko", "blog-ja", "blog-zh"])
def test_durable_global_interval_is_shared_across_blog_targets(monkeypatch, blog_id):
    """A newly constructed worker reads the same DB interval and last-write anchor."""
    from contextlib import contextmanager

    from woori import blogger_writes

    started_at = datetime.now(UTC) - timedelta(minutes=12)
    queries = []

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

    class Connection:
        def execute(self, query, _params=()):
            queries.append(query)
            if "pg_try_advisory_lock" in query:
                return Result({"acquired": True})
            if "SELECT max(a.created_at)" in query:
                return Result({"last_write": started_at, "blog_hourly": 0})
            if "global_publish_min_interval_minutes" in query:
                return Result({"global_publish_min_interval_minutes": 15})
            return Result({"unlocked": True})

    @contextmanager
    def shared_connection():
        yield Connection()

    monkeypatch.setattr(blogger_writes, "connection", shared_connection)
    with pytest.raises(blogger_writes.WriteIntervalWait) as exc, \
            blogger_writes.BloggerLivePublisher._account_write_guard(
                {"oauth_connection_id": "shared-grant", "blog_id": blog_id,
                 "language_code": "en"}
            ):
        pytest.fail("a different Blogger must not bypass the durable global interval")
    assert exc.value.available_at == started_at + timedelta(minutes=15)
    assert any("external.call.started" in query and "'POST','PATCH','PUT'" in query for query in queries)


def test_global_write_lock_rejects_concurrent_worker(monkeypatch):
    from contextlib import contextmanager

    from woori import blogger_writes

    class Result:
        def fetchone(self):
            return {"acquired": False}

    class Connection:
        def execute(self, *_args, **_kwargs):
            return Result()

    @contextmanager
    def shared_connection():
        yield Connection()

    monkeypatch.setattr(blogger_writes, "connection", shared_connection)
    with pytest.raises(blogger_writes.GoogleFailure, match="account_write_in_progress"), \
            blogger_writes.BloggerLivePublisher._account_write_guard(
                {"oauth_connection_id": "shared-grant", "blog_id": "blog-en",
                 "language_code": "en"}
            ):
        pytest.fail("the second worker must not start a parallel Blogger write")


def test_guard_stops_before_http_and_binds_spacing_to_selected_oauth(monkeypatch):
    from contextlib import contextmanager

    from woori import blogger_writes
    from woori.blogger_writes import WriteIntervalWait
    now=datetime.now(UTC)
    params_seen=[]
    class Conn:
        def execute(self,query,params=()):
            params_seen.append(params)
            self.limits='SELECT max' in query
            self.controls='global_publish_min_interval_minutes' in query
            return self
        def fetchone(self):
            if self.limits:return {'last_write':now,'blog_hourly':0}
            if self.controls:return {'global_publish_min_interval_minutes':15}
            return {'acquired':True}
    @contextmanager
    def shared():
        yield Conn()
    monkeypatch.setattr(blogger_writes,'connection',shared)
    with pytest.raises(WriteIntervalWait) as exc, blogger_writes.BloggerLivePublisher._account_write_guard({'oauth_connection_id':'selected-grant','blog_id':'selected-blog','language_code':'en'}):
        pytest.fail('write must not begin before its interval')
    assert exc.value.available_at>=now+timedelta(minutes=14,seconds=59)
    assert ('blogger-global-publication-write',) in params_seen
