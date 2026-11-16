from datetime import UTC, datetime, timedelta

import pytest
from woori.publication_read_state import pending_state
from woori.publications import publication_list_flow


@pytest.mark.parametrize(('lane','fresh','allowed','expected'),[
    ('trends_auto',True,True,'auto_paused'), ('scheduled_auto',True,True,'auto_paused'),
    ('manual',False,True,'auto_paused'), ('manual',True,False,'manual_action_required'),
    ('manual',True,True,'queued')])
def test_only_fresh_explicit_permitted_manual_job_is_queued(lane,fresh,allowed,expected):
    cutoff=datetime.now(UTC)
    approval=cutoff+timedelta(seconds=1 if fresh else -1)
    assert pending_state(lane,approval,cutoff,allowed)==expected


def test_verified_draft_is_not_live_and_pause_is_not_processing():
    assert publication_list_flow({'remote_post_id':'123','remote_verified_at':True,'remote_status':'DRAFT'})=='draft_saved'
    assert publication_list_flow({'active_job_id':'job','active_job_status':'queued','pending_operational_state':'auto_paused'})=='auto_paused'


def test_shared_queue_counts_preserve_raw_queue_but_never_count_auto_as_dispatchable():
    from woori.publication_read_state import dispatch_queue_counts
    now=datetime.now(UTC)
    class Rows:
        def __init__(self,rows): self.rows=rows
        def fetchone(self): return self.rows[0]
        def fetchall(self): return self.rows
    class Conn:
        def execute(self,query):
            if 'FROM publication_mode_settings' in query:
                return Rows([{'blogger_write_mode':'manual_only','blogger_api_restricted':True,'emergency_stopped':True}])
            if 'FROM worker_heartbeats' in query:
                return Rows([{'status':'running','last_seen_at':now,'execution_mode':'operations-manual-confirmed'}])
            if 'max(created_at) cutoff' in query:
                return Rows([{'cutoff':now}])
            return Rows([{'publication_lane':'trends_auto','approval_at':None,'scheduled_at':now,'available_at':now}])
    result=dispatch_queue_counts(Conn())
    assert result['live_queued']==result['live_due']==0
    assert result['preserved_live_queued']==result['auto_paused']==1
