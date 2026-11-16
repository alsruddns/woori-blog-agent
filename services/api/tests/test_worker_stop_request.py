from datetime import UTC, datetime, timedelta

from woori import worker


def _request(root, *, pid=123, service="research_worker", started=None):
    return {
        "pid": pid,
        "service": service,
        "checkout_root": str(root),
        "process_started_at": (started or datetime.now(UTC)).isoformat(),
    }


def test_worker_stop_request_requires_exact_process_identity(tmp_path):
    started = datetime.now(UTC)
    request = _request(tmp_path, started=started)

    assert worker.worker_stop_request_matches(
        request, pid=123, service_name="research_worker", checkout_root=tmp_path,
        process_started_at=started + timedelta(milliseconds=500),
    )
    assert not worker.worker_stop_request_matches(
        request, pid=124, service_name="research_worker", checkout_root=tmp_path,
        process_started_at=started,
    )
    assert not worker.worker_stop_request_matches(
        request, pid=123, service_name="evaluation_worker", checkout_root=tmp_path,
        process_started_at=started,
    )
    assert not worker.worker_stop_request_matches(
        request, pid=123, service_name="research_worker", checkout_root=tmp_path / "other",
        process_started_at=started,
    )
    assert not worker.worker_stop_request_matches(
        request, pid=123, service_name="research_worker", checkout_root=tmp_path,
        process_started_at=started + timedelta(seconds=3),
    )
    assert not worker.worker_stop_request_matches(
        request, pid=123, service_name="research_worker", checkout_root=tmp_path,
        process_started_at=None,
    )


def test_consume_stop_request_leaves_pid_reuse_marker_untouched(tmp_path, monkeypatch):
    marker = tmp_path / ".runtime" / "worker-stop-123.json"
    marker.parent.mkdir()
    started = datetime.now(UTC)
    marker.write_text(worker.json.dumps(_request(tmp_path, started=started)), encoding="utf-8")
    monkeypatch.setattr(worker, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(worker, "_windows_process_started_at", lambda _pid: started + timedelta(seconds=10))

    assert not worker.consume_worker_stop_request(pid=123, service_name="research_worker")
    assert marker.exists()


def test_consume_stop_request_removes_only_matching_marker(tmp_path, monkeypatch):
    marker = tmp_path / ".runtime" / "worker-stop-123.json"
    marker.parent.mkdir()
    started = datetime.now(UTC)
    marker.write_text(worker.json.dumps(_request(tmp_path, started=started)), encoding="utf-8")
    monkeypatch.setattr(worker, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(worker, "_windows_process_started_at", lambda _pid: started)

    assert worker.consume_worker_stop_request(pid=123, service_name="research_worker")
    assert not marker.exists()
