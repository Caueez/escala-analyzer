"""Claim jobs atomically and discard results from stale or cancelled executions."""

import logging
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update

from escala_analyzer.domain.analysis.project_analyzer import ProjectAnalyzer
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.domain.optimization.optimization_options import OptimizationOptions
from escala_analyzer.infrastructure.database.connection import Database
from escala_analyzer.infrastructure.database.models import Job, User, utcnow
from escala_analyzer.infrastructure.optimization.schedule_optimizer import ScheduleOptimizer
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec
from escala_analyzer.settings import Settings

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    def execute(self, job_id: str) -> str:
        execution = str(uuid4())
        with self.database.sessions.begin() as session:
            claimed = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.state == "queued")
                .values(
                    state="running",
                    execution_id=execution,
                    lease_until=utcnow() + timedelta(seconds=self.settings.job_lease_seconds),
                    attempts=Job.attempts + 1,
                )
                .returning(Job.id)
            ).scalar_one_or_none()
            if claimed is None:
                return "ignored"
            job = session.get(Job, job_id)
            assert job is not None
            payload, kind = job.payload, job.kind
            user = session.scalar(
                select(User).where(
                    User.id == job.owner_id,
                    User.organization_id == job.organization_id,
                    User.active.is_(True),
                )
            )
            allowed = user is not None
            compatible = job.rules_version == self.settings.rules_version
        try:
            if not compatible:
                self.finish(job_id, execution, None, "rules_version_changed")
                return "failed"
            if not allowed:
                self.finish(job_id, execution, None, "owner_inactive")
                return "failed"
            result = self.calculate(kind, payload)
        except Exception:  # noqa: BLE001 — fault boundary records a safe status for retry/operations.
            logger.error("job_failed job_id=%s execution_id=%s", job_id, execution)
            self.finish(job_id, execution, None, "calculation_failed")
            return "failed"
        self.finish(job_id, execution, result, None)
        return "completed"

    @staticmethod
    def calculate(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = EntityCodec.load(ProjectState, payload["project"])
        if kind == "optimization":
            options = EntityCodec.load(OptimizationOptions, payload["options"])
            return dict(ScheduleOptimizer().optimize(project, options))
        return dict(ProjectAnalyzer().analyze(project))

    def finish(
        self, job_id: str, execution: str, result: dict[str, Any] | None, error: str | None
    ) -> None:
        with self.database.sessions.begin() as session:
            session.execute(
                update(Job)
                .where(Job.id == job_id, Job.execution_id == execution, Job.state == "running")
                .values(
                    state="failed" if error else "succeeded",
                    result=result,
                    error_code=error,
                    finished_at=utcnow(),
                    lease_until=None,
                )
            )
