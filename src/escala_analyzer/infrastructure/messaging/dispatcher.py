"""Publish committed outbox rows with confirmation; duplicates are safe."""

import logging
import time
from datetime import timedelta
from typing import Protocol

from sqlalchemy import select

from escala_analyzer.infrastructure.database.connection import Database
from escala_analyzer.infrastructure.database.models import Job, OutboxMessage, utcnow
from escala_analyzer.infrastructure.database.retention import Retention
from escala_analyzer.infrastructure.observability.logging import configure_logging
from escala_analyzer.settings import Settings

logger = logging.getLogger("escala.dispatcher")


class Publisher(Protocol):
    def publish(self, job_id: str, queue: str) -> None: ...


class CeleryPublisher:
    def publish(self, job_id: str, queue: str) -> None:
        from .celery_app import celery_app

        celery_app.send_task("escala.execute", args=[job_id], queue=queue, retry=False)


class OutboxDispatcher:
    def __init__(self, database: Database, publisher: Publisher) -> None:
        self.database = database
        self.publisher = publisher

    def dispatch(self, limit: int = 20) -> int:
        delivered = 0
        with self.database.sessions.begin() as session:
            messages = session.scalars(
                select(OutboxMessage)
                .where(
                    OutboxMessage.published_at.is_(None), OutboxMessage.next_attempt_at <= utcnow()
                )
                .order_by(OutboxMessage.next_attempt_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for message in messages:
                job = session.get(Job, message.job_id)
                if not job or job.state != "queued":
                    message.published_at = utcnow()
                    continue
                message.attempts += 1
                try:
                    self.publisher.publish(message.job_id, message.queue)
                except Exception:  # noqa: BLE001 — fault boundary records a safe status for retry/operations.
                    # No URLs/credentials or project payloads go into logs.
                    logger.warning(
                        "outbox_publish_failed job_id=%s attempt=%s",
                        message.job_id,
                        message.attempts,
                    )
                    message.next_attempt_at = utcnow() + timedelta(
                        seconds=min(60, 2 ** min(message.attempts, 6))
                    )
                else:
                    message.published_at = utcnow()
                    delivered += 1
        return delivered

    def recover_expired(self) -> int:
        with self.database.sessions.begin() as session:
            jobs = session.scalars(
                select(Job)
                .where(Job.state == "running", Job.lease_until < utcnow())
                .with_for_update(skip_locked=True)
            ).all()
            for job in jobs:
                if job.attempts >= 3:
                    job.state = "failed"
                    job.error_code = "worker_attempts_exhausted"
                    job.finished_at = utcnow()
                else:
                    job.state = "queued"
                    job.execution_id = None
                    message = session.scalar(
                        select(OutboxMessage).where(OutboxMessage.job_id == job.id)
                    )
                    if message:
                        message.published_at = None
                        message.next_attempt_at = utcnow()
            # A confirmed message can still disappear after operator purge or broker
            # storage loss. Re-publication is safe because workers claim by CAS.
            pending = session.scalars(
                select(OutboxMessage)
                .join(Job)
                .where(
                    Job.state == "queued",
                    OutboxMessage.published_at < utcnow() - timedelta(seconds=60),
                )
                .with_for_update(skip_locked=True)
            ).all()
            for message in pending:
                message.published_at = None
                message.next_attempt_at = utcnow()
            return len(jobs)


def main() -> None:
    configure_logging()
    settings = Settings()
    dispatcher = OutboxDispatcher(Database(settings.database_url), CeleryPublisher())
    logging.basicConfig(level=logging.INFO)
    next_cleanup = 0.0
    while True:
        try:
            if time.monotonic() >= next_cleanup:
                Retention.cleanup(dispatcher.database, settings.job_retention_days)
                next_cleanup = time.monotonic() + 3600
            dispatcher.recover_expired()
            dispatcher.dispatch()
        except Exception:  # noqa: BLE001 — fault boundary records a safe status for retry/operations.
            logger.error("outbox_database_unavailable")
        time.sleep(2)


if __name__ == "__main__":
    main()
