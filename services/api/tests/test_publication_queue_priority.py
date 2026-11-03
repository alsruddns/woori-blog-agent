from woori import automation_auto, publication_operation, publication_worker


def test_new_scheduled_job_is_dispatched_before_other_queue_lanes(monkeypatch):
    calls = []
    scheduled = {"job_id": "new-scheduled", "status": "published"}

    def auto_tick(*, origin_filter=None):
        calls.append(("auto", origin_filter))
        return scheduled if origin_filter == "scheduled" else None

    monkeypatch.setattr(automation_auto, "tick", auto_tick)
    monkeypatch.setattr(publication_worker, "process_next_live_job", lambda **kwargs: calls.append(("process", kwargs)) or None)
    monkeypatch.setattr(publication_operation, "manual_requests_allowed", lambda: True)

    result = publication_worker.tick(
        allow_scheduled_auto_publications=True,
        allow_manual_confirmed_publications=True,
        allow_trends_auto_publications=True,
    )

    assert result["job_id"] == "new-scheduled"
    assert calls == [("auto", "scheduled")]


def test_manual_queue_precedes_trends_after_scheduled_lane_is_empty(monkeypatch):
    calls = []
    manual = {"job_id": "manual-request", "status": "queued"}

    def auto_tick(*, origin_filter=None):
        calls.append(("auto", origin_filter))

    def process_next(**kwargs):
        calls.append(("process", kwargs))
        return manual if kwargs.get("manual_confirmed_only") else None

    monkeypatch.setattr(automation_auto, "tick", auto_tick)
    monkeypatch.setattr(publication_worker, "process_next_live_job", process_next)
    monkeypatch.setattr(publication_operation, "manual_requests_allowed", lambda: True)

    result = publication_worker.tick(
        allow_scheduled_auto_publications=True,
        allow_manual_confirmed_publications=True,
        allow_trends_auto_publications=True,
    )

    assert result["job_id"] == "manual-request"
    assert calls == [
        ("auto", "scheduled"),
        ("process", {"scheduled_auto_only": True}),
        ("process", {"manual_confirmed_only": True}),
    ]
