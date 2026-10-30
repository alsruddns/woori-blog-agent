from datetime import UTC, datetime, timedelta

import pytest
from woori.blogger_writes import interval_deadline


@pytest.mark.parametrize(('account_age','blog_age','wait'),[
    (None,None,0),(30,None,90),(None,10,290),(10,10,290),(121,301,0),
    (120,300,0),(0,299,120),
])
def test_deadline_preserves_both_request_scopes(account_age,blog_age,wait):
    now=datetime(2026,10,30,7,tzinfo=UTC)
    assert interval_deadline(now-timedelta(seconds=account_age) if account_age is not None else None,
                             now-timedelta(seconds=blog_age) if blog_age is not None else None,now)==now+timedelta(seconds=wait)


def test_guard_stops_before_http_and_binds_spacing_to_selected_oauth(monkeypatch):
    from contextlib import contextmanager

    from woori import blogger_writes
    from woori.blogger_writes import WriteIntervalWait
    now=datetime.now(UTC)
    params_seen=[]
    class Conn:
        def execute(self,query,params):
            params_seen.append(params)
            self.limits='SELECT max' in query
            return self
        def fetchone(self):
            return {'account_last':now,'blog_last':None,'blog_hourly':0} if self.limits else {'acquired':True}
    @contextmanager
    def shared():
        yield Conn()
    monkeypatch.setattr(blogger_writes,'connection',shared)
    with pytest.raises(WriteIntervalWait) as exc, blogger_writes.BloggerLivePublisher._account_write_guard({'oauth_connection_id':'selected-grant','blog_id':'selected-blog','language_code':'en'}):
        pytest.fail('write must not begin before its interval')
    assert exc.value.available_at==now+timedelta(minutes=2)
    assert ('selected-grant','selected-blog','selected-blog') in params_seen
