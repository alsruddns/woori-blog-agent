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
