from datetime import timedelta
from uuid import uuid4

import pytest
from conftest import PASSWORD
from sqlalchemy import event, func, select

from escala_analyzer.cli import Administration
from escala_analyzer.infrastructure.database.models import Job, OutboxMessage, utcnow
from escala_analyzer.infrastructure.messaging.dispatcher import OutboxDispatcher
from escala_analyzer.infrastructure.messaging.runner import JobRunner


def submit(saas, key=None):
    project = saas.client.get("/api/project").json()
    response = saas.client.post(
        "/api/analyze", json=project, headers={"Idempotency-Key": key or str(uuid4())}
    )
    assert response.status_code == 202, response.text
    return response.json()


class RecordingPublisher:
    def __init__(self, fail=False):
        self.fail = fail
        self.messages = []

    def publish(self, job_id, queue):
        if self.fail:
            raise ConnectionError("broker unavailable")
        self.messages.append((job_id, queue))


def test_api_never_executes_the_calculation_and_job_has_durable_outbox(saas, monkeypatch):
    saas.login()
    monkeypatch.setattr(
        JobRunner, "calculate", staticmethod(lambda *args: pytest.fail("must run in worker"))
    )
    job = submit(saas)
    assert job["state"] == "queued"
    assert saas.client.get(job["result_url"]).status_code == 409
    with saas.database.sessions() as session:
        assert (
            session.scalar(select(OutboxMessage).where(OutboxMessage.job_id == job["id"]))
            is not None
        )


def test_job_idempotency_quota_and_key_payload_conflict(saas):
    saas.login()
    key = str(uuid4())
    first, repeat = submit(saas, key), submit(saas, key)
    assert first["id"] == repeat["id"]
    project = saas.client.get("/api/project").json()
    project["name"] = "different"
    assert (
        saas.client.post("/api/analyze", json=project, headers={"Idempotency-Key": key}).status_code
        == 409
    )
    for _ in range(3):
        submit(saas)
    assert (
        saas.client.post(
            "/api/analyze", json=project, headers={"Idempotency-Key": str(uuid4())}
        ).status_code
        == 429
    )
    assert submit(saas, key)["id"] == first["id"]


def test_outbox_publication_failure_does_not_lose_a_job(saas):
    saas.login()
    job = submit(saas)
    publisher = RecordingPublisher(fail=True)
    dispatcher = OutboxDispatcher(saas.database, publisher)
    assert dispatcher.dispatch() == 0
    with saas.database.sessions.begin() as session:
        message = session.scalar(select(OutboxMessage))
        assert message.published_at is None
        assert message.attempts == 1
        message.next_attempt_at = utcnow() - timedelta(seconds=1)
    publisher.fail = False
    assert dispatcher.dispatch() == 1
    assert publisher.messages == [(job["id"], "analysis")]
    assert dispatcher.dispatch() == 0


def test_outbox_insert_and_job_acceptance_are_atomic(saas):
    saas.login()
    principal = saas.client.app.state.authentication.resolve(saas.client.cookies["escala_session"])

    def reject_insert(*args):
        raise RuntimeError("simulated insert failure")

    event.listen(OutboxMessage, "before_insert", reject_insert)
    try:
        with pytest.raises(RuntimeError):
            saas.client.app.state.jobs.enqueue(principal, "analysis", {"project": {}}, str(uuid4()))
    finally:
        event.remove(OutboxMessage, "before_insert", reject_insert)
    with saas.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0


def test_worker_completes_duplicate_delivery_only_once_and_never_saves_project(saas):
    saas.login()
    before = saas.client.get("/api/project").json()
    job = submit(saas)
    runner = JobRunner(saas.database, saas.settings)
    assert runner.execute(job["id"]) == "completed"
    assert runner.execute(job["id"]) == "ignored"
    assert saas.client.get(job["status_url"]).json()["state"] == "succeeded"
    assert saas.client.get(job["result_url"]).json()["year"] == before["year"]
    assert saas.client.get("/api/project").json() == before
    with saas.database.sessions() as session:
        assert session.get(Job, job["id"]).attempts == 1


def test_expired_worker_lease_is_requeued_and_stale_completion_is_ignored(saas):
    saas.login()
    job = submit(saas)
    with saas.database.sessions.begin() as session:
        record = session.get(Job, job["id"])
        record.state, record.execution_id = "running", "old-execution"
        record.attempts = 1
        record.lease_until = utcnow() - timedelta(seconds=1)
    dispatcher = OutboxDispatcher(saas.database, RecordingPublisher())
    assert dispatcher.recover_expired() == 1
    runner = JobRunner(saas.database, saas.settings)
    runner.finish(job["id"], "old-execution", {"invalid": "stale"}, None)
    assert runner.execute(job["id"]) == "completed"
    assert "invalid" not in saas.client.get(job["result_url"]).json()


def test_exhausted_crashes_end_in_failure(saas):
    saas.login()
    job = submit(saas)
    with saas.database.sessions.begin() as session:
        record = session.get(Job, job["id"])
        record.state, record.attempts = "running", 3
        record.lease_until = utcnow() - timedelta(seconds=1)
    OutboxDispatcher(saas.database, RecordingPublisher()).recover_expired()
    assert saas.client.get(job["status_url"]).json()["error_code"] == "worker_attempts_exhausted"


def test_cancelling_running_job_discards_result(saas, monkeypatch):
    saas.login()
    job = submit(saas)
    principal = saas.client.app.state.authentication.resolve(saas.client.cookies["escala_session"])

    def cancellation(*args):
        saas.client.app.state.jobs.cancel(principal, job["id"])
        return {"should_not_be_persisted": True}

    monkeypatch.setattr(JobRunner, "calculate", staticmethod(cancellation))
    JobRunner(saas.database, saas.settings).execute(job["id"])
    assert saas.client.get(job["status_url"]).json()["state"] == "cancelled"
    assert saas.client.get(job["result_url"]).status_code == 409


def test_job_result_and_cancellation_cannot_cross_tenants(saas):
    saas.login()
    job = submit(saas)
    JobRunner(saas.database, saas.settings).execute(job["id"])
    Administration(saas.database).provision("Other", "another@example.com", "Other", PASSWORD)
    saas.login("another@example.com")
    for path in (job["status_url"], job["result_url"]):
        assert saas.client.get(path).status_code == 404
    assert saas.client.post(job["status_url"] + "/cancel").status_code == 404


def test_worker_records_safe_failure_without_exposing_payload_or_exception(saas, monkeypatch):
    saas.login()
    job = submit(saas)

    def fail(*args):
        raise ValueError("private payload must not leak")

    monkeypatch.setattr(JobRunner, "calculate", staticmethod(fail))
    assert JobRunner(saas.database, saas.settings).execute(job["id"]) == "failed"
    response = saas.client.get(job["status_url"])
    assert response.json()["error_code"] == "calculation_failed"
    assert "private payload" not in response.text


def test_published_but_lost_message_is_republished(saas):
    saas.login()
    job = submit(saas)
    publisher = RecordingPublisher()
    dispatcher = OutboxDispatcher(saas.database, publisher)
    assert dispatcher.dispatch() == 1
    with saas.database.sessions.begin() as session:
        message = session.scalar(select(OutboxMessage).where(OutboxMessage.job_id == job["id"]))
        message.published_at = utcnow() - timedelta(seconds=61)
    dispatcher.recover_expired()
    assert dispatcher.dispatch() == 1
    assert len(publisher.messages) == 2


def test_worker_rejects_job_from_another_rule_version(saas):
    saas.login()
    job = submit(saas)
    with saas.database.sessions.begin() as session:
        session.get(Job, job["id"]).rules_version = "old-rules"
    assert JobRunner(saas.database, saas.settings).execute(job["id"]) == "failed"
    assert saas.client.get(job["status_url"]).json()["error_code"] == "rules_version_changed"


def test_deactivated_owner_job_is_not_computed(saas, monkeypatch):
    from escala_analyzer.infrastructure.database.models import User

    saas.login()
    job = submit(saas)
    with saas.database.sessions.begin() as session:
        session.get(User, saas.admin_id).active = False
    monkeypatch.setattr(
        JobRunner, "calculate", staticmethod(lambda *args: pytest.fail("inactive owner"))
    )
    assert JobRunner(saas.database, saas.settings).execute(job["id"]) == "failed"
    with saas.database.sessions() as session:
        assert session.get(Job, job["id"]).error_code == "owner_inactive"
