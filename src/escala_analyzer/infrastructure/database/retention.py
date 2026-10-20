"""Operational retention of completed jobs and expired authentication material."""

from datetime import timedelta

from sqlalchemy import delete

from .connection import Database
from .models import Job, LoginSession, RateLimit, utcnow


class Retention:
    @staticmethod
    def cleanup(database: Database, job_days: int) -> None:
        with database.sessions.begin() as session:
            session.execute(
                delete(Job).where(
                    Job.finished_at < utcnow() - timedelta(days=job_days),
                    Job.state.in_(["failed", "succeeded", "cancelled"]),
                )
            )
            session.execute(delete(LoginSession).where(LoginSession.expires_at < utcnow()))
            session.execute(delete(RateLimit).where(RateLimit.resets_at < utcnow()))
