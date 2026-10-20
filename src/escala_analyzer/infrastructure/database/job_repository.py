"""Durable job acceptance and outbox insertion in the same transaction."""

import hashlib
import json
from typing import Any

from sqlalchemy import func, select

from escala_analyzer.application.services.errors import CapacityError, ConflictError, NotFoundError
from escala_analyzer.application.services.identity import Principal
from escala_analyzer.infrastructure.database.connection import Database
from escala_analyzer.infrastructure.database.models import (
    AuditEvent,
    Job,
    Organization,
    OutboxMessage,
    utcnow,
)
from escala_analyzer.settings import Settings


class JobRepository:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    def enqueue(self, principal: Principal, kind: str, payload: dict[str, Any], key: str) -> Job:
        fingerprint = hashlib.sha256(
            json.dumps(
                {"kind": kind, "payload": payload}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        with self.database.sessions.begin() as session:
            session.scalar(
                select(Organization)
                .where(Organization.id == principal.organization_id)
                .with_for_update()
            )
            existing = session.scalar(
                select(Job).where(
                    Job.organization_id == principal.organization_id,
                    Job.owner_id == principal.user_id,
                    Job.idempotency_key == key,
                )
            )
            if existing:
                if existing.request_hash != fingerprint:
                    raise ConflictError("Chave de idempotência reutilizada com outro conteúdo.")
                return existing
            active = (
                session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(
                        Job.organization_id == principal.organization_id,
                        Job.state.in_(["queued", "running"]),
                    )
                )
                or 0
            )
            if active >= self.settings.max_active_jobs:
                raise CapacityError("Limite de trabalhos ativos atingido. Aguarde a conclusão.")
            job = Job(
                organization_id=principal.organization_id,
                owner_id=principal.user_id,
                kind=kind,
                payload=payload,
                idempotency_key=key,
                request_hash=fingerprint,
                rules_version=self.settings.rules_version,
            )
            session.add(job)
            session.flush()
            session.add(
                OutboxMessage(
                    job_id=job.id, queue="optimization" if kind == "optimization" else "analysis"
                )
            )
            session.add(
                AuditEvent(
                    organization_id=principal.organization_id,
                    actor_id=principal.user_id,
                    action="job.queued",
                    entity_id=job.id,
                )
            )
            return job

    def get(self, principal: Principal, job_id: str) -> Job:
        with self.database.sessions() as session:
            job = session.scalar(
                select(Job).where(
                    Job.id == job_id, Job.organization_id == principal.organization_id
                )
            )
            if not job:
                raise NotFoundError("Trabalho não encontrado.")
            return job

    def cancel(self, principal: Principal, job_id: str) -> Job:
        with self.database.sessions.begin() as session:
            job = session.scalar(
                select(Job)
                .where(Job.id == job_id, Job.organization_id == principal.organization_id)
                .with_for_update()
            )
            if not job:
                raise NotFoundError("Trabalho não encontrado.")
            if job.owner_id != principal.user_id and principal.role != "admin":
                raise NotFoundError("Trabalho não encontrado.")
            if job.state in {"queued", "running"}:
                job.state = "cancelled"
                job.finished_at = utcnow()
                session.add(
                    AuditEvent(
                        organization_id=principal.organization_id,
                        actor_id=principal.user_id,
                        action="job.cancelled",
                        entity_id=job.id,
                    )
                )
            return job
