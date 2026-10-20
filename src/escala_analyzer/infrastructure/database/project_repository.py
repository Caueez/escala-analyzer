"""Tenant-scoped, atomic project snapshots with compare-and-swap revisions."""

from copy import deepcopy
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from escala_analyzer.application.services.errors import NotFoundError, PreconditionError
from escala_analyzer.application.services.identity import Principal
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.infrastructure.database.connection import Database
from escala_analyzer.infrastructure.database.models import (
    AuditEvent,
    Organization,
    Project,
    User,
    UserPreference,
    utcnow,
)
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec


class SqlProjectRepository:
    def __init__(self, database: Database, principal: Principal) -> None:
        self.database = database
        self.principal = principal

    def list_projects(self) -> list[tuple[ProjectState, int]]:
        with self.database.sessions() as session:
            rows = session.scalars(
                select(Project)
                .where(Project.organization_id == self.principal.organization_id)
                .order_by(Project.updated_at, Project.id)
            ).all()
            return [(EntityCodec.load(ProjectState, row.payload), row.revision) for row in rows]

    def load(self, project_id: str | None = None) -> tuple[ProjectState, int]:
        with self.database.sessions.begin() as session:
            if project_id is None:
                preference = session.get(UserPreference, self.principal.user_id)
                if preference:
                    project_id = preference.project_id
                if not project_id:
                    project_id = session.scalar(
                        select(Project.id)
                        .where(Project.organization_id == self.principal.organization_id)
                        .order_by(Project.updated_at)
                        .limit(1)
                    )
            row = (
                session.get(Project, (self.principal.organization_id, project_id))
                if project_id
                else None
            )
            if not row:
                raise NotFoundError("Projeto não encontrado.")
            session.merge(UserPreference(user_id=self.principal.user_id, project_id=row.id))
            return EntityCodec.load(ProjectState, row.payload), row.revision

    def save(
        self,
        project: ProjectState,
        expected_revision: int,
        related: list[ProjectState] | None = None,
    ) -> int:
        if related:
            raise ValueError("Use importação transacional para múltiplos projetos.")
        with self.database.sessions.begin() as session:
            # All writes lock the tenant before the project: stable lock ordering also
            # makes group propagation, initial creation and deletion atomic.
            session.scalar(
                select(Organization)
                .where(Organization.id == self.principal.organization_id)
                .with_for_update()
            )
            existing = session.get(Project, (self.principal.organization_id, project.project_id))
            if existing is None:
                count = (
                    session.scalar(
                        select(func.count())
                        .select_from(Project)
                        .where(Project.organization_id == self.principal.organization_id)
                    )
                    or 0
                )
                if count >= 100:
                    raise ValueError("Limite de 100 subdivisões atingido.")
                if expected_revision != 0:
                    raise PreconditionError(
                        "O projeto mudou ou foi removido. Recarregue antes de salvar."
                    )
                session.add(
                    Project(
                        organization_id=self.principal.organization_id,
                        id=project.project_id,
                        payload=EntityCodec.dump(project, mode="json"),
                        revision=1,
                    )
                )
                revision = 1
            else:
                changed = session.execute(
                    update(Project)
                    .where(
                        Project.organization_id == self.principal.organization_id,
                        Project.id == project.project_id,
                        Project.revision == expected_revision,
                    )
                    .values(
                        payload=EntityCodec.dump(project, mode="json"),
                        revision=expected_revision + 1,
                        updated_at=utcnow(),
                    )
                    .returning(Project.revision)
                ).scalar_one_or_none()
                if changed is None:
                    raise PreconditionError(
                        "Outra sessão alterou o projeto. Recarregue antes de salvar."
                    )
                revision = expected_revision + 1
            session.flush()
            self.propagate_links(session, project)
            session.merge(
                UserPreference(user_id=self.principal.user_id, project_id=project.project_id)
            )
            self.audit(session, "project.saved", project.project_id)
            return revision

    def propagate_links(self, session: Session, project: ProjectState) -> None:
        definitions = {}
        for group in project.groups:
            link = project.shared_group_links.get(group.id)
            if not link:
                continue
            definition = EntityCodec.dump(group, mode="json")
            definition.pop("id")
            if link in definitions and definitions[link] != definition:
                raise ValueError("Grupos vinculados receberam alterações conflitantes.")
            definitions[link] = definition
        rows = session.scalars(
            select(Project).where(
                Project.organization_id == self.principal.organization_id,
                Project.id != project.project_id,
            )
        ).all()
        for row in rows:
            payload = deepcopy(row.payload)
            if payload.get("portfolio_id") == project.portfolio_id:
                payload["portfolio_name"] = project.portfolio_name
            for gid, link in payload.get("shared_group_links", {}).items():
                if link in definitions:
                    payload["groups"] = [
                        dict(definitions[link], id=gid) if group["id"] == gid else group
                        for group in payload["groups"]
                    ]
            if payload != row.payload:
                EntityCodec.load(ProjectState, payload)
                row.payload = payload
                row.revision += 1
                row.updated_at = utcnow()

    def import_projects(self, projects: list[ProjectState], active_id: str) -> None:
        # Import creates fresh local identifiers. Existing projects are never overwritten
        # by a file carrying guessed identifiers or obsolete revisions.
        if (
            not projects
            or len(projects) > 100
            or len({p.project_id for p in projects}) != len(projects)
            or active_id not in {p.project_id for p in projects}
        ):
            raise ValueError("Backup inválido ou acima do limite de 100 subdivisões.")
        with self.database.sessions.begin() as session:
            session.scalar(
                select(Organization)
                .where(Organization.id == self.principal.organization_id)
                .with_for_update()
            )
            existing_count = (
                session.scalar(
                    select(func.count())
                    .select_from(Project)
                    .where(Project.organization_id == self.principal.organization_id)
                )
                or 0
            )
            if existing_count + len(projects) > 100:
                raise ValueError("A importação excede o limite de 100 subdivisões por empresa.")
            links: dict[str, str] = {}
            portfolios: dict[str, str] = {}
            for project in projects:
                old_id = project.project_id
                project.project_id = str(uuid4())
                project.portfolio_id = portfolios.setdefault(project.portfolio_id, str(uuid4()))
                project.shared_group_links = {
                    gid: links.setdefault(link, str(uuid4()))
                    for gid, link in project.shared_group_links.items()
                }
                session.add(
                    Project(
                        organization_id=self.principal.organization_id,
                        id=project.project_id,
                        payload=EntityCodec.dump(project, mode="json"),
                        revision=1,
                    )
                )
                if old_id == active_id:
                    session.merge(
                        UserPreference(
                            user_id=self.principal.user_id, project_id=project.project_id
                        )
                    )
            self.audit(session, "project.imported", str(len(projects)))

    def delete(self, project_id: str, revision: int) -> None:
        with self.database.sessions.begin() as session:
            session.scalar(
                select(Organization)
                .where(Organization.id == self.principal.organization_id)
                .with_for_update()
            )
            rows = session.scalars(
                select(Project).where(Project.organization_id == self.principal.organization_id)
            ).all()
            row = next((item for item in rows if item.id == project_id), None)
            if not row:
                raise NotFoundError("Projeto não encontrado.")
            if row.revision != revision:
                raise PreconditionError("O projeto mudou. Recarregue antes de excluir.")
            if len(rows) <= 1:
                raise ValueError("Mantenha ao menos uma subdivisão.")
            session.delete(row)
            session.execute(
                update(UserPreference)
                .where(
                    UserPreference.project_id == project_id,
                    UserPreference.user_id.in_(
                        select(User.id).where(
                            User.organization_id == self.principal.organization_id
                        )
                    ),
                )
                .values(project_id=None)
            )
            self.audit(session, "project.deleted", project_id)

    def reuse(
        self, target_id: str, source_id: str, group_id: str, linked: bool, expected_revision: int
    ) -> tuple[ProjectState, int]:
        with self.database.sessions.begin() as session:
            session.scalar(
                select(Organization)
                .where(Organization.id == self.principal.organization_id)
                .with_for_update()
            )
            source_row = session.get(Project, (self.principal.organization_id, source_id))
            target_row = session.get(Project, (self.principal.organization_id, target_id))
            if source_row is None or target_row is None:
                raise NotFoundError("Projeto não encontrado.")
            if target_row.revision != expected_revision:
                raise PreconditionError("O projeto mudou. Recarregue antes de reutilizar grupos.")
            source = EntityCodec.load(ProjectState, source_row.payload)
            target = (
                source
                if source_id == target_id
                else EntityCodec.load(ProjectState, target_row.payload)
            )
            group = next((item for item in source.groups if item.id == group_id), None)
            if group is None:
                raise NotFoundError("Grupo não encontrado.")
            needed = set(group.allocations) | set(group.rotation_shift_ids)
            for shift in source.shifts:
                if shift.id not in needed:
                    continue
                existing = next((item for item in target.shifts if item.id == shift.id), None)
                if existing is not None and existing != shift:
                    raise ValueError("Turnos com mesmo identificador e configurações diferentes.")
                if existing is None:
                    target.shifts.append(deepcopy(shift))
            copied = deepcopy(group)
            copied.id = str(uuid4())
            target.groups.append(copied)
            if linked:
                link = source.shared_group_links.get(group.id, str(uuid4()))
                source.shared_group_links[group.id] = link
                target.shared_group_links[copied.id] = link
                if source_id != target_id:
                    source_row.payload = EntityCodec.dump(source, mode="json")
                    source_row.revision += 1
                    source_row.updated_at = utcnow()
            from escala_analyzer.application.services.job_policy import JobPolicy

            JobPolicy.validate(target)
            EntityCodec.load(ProjectState, EntityCodec.dump(target))
            target_row.payload = EntityCodec.dump(target, mode="json")
            target_row.revision += 1
            target_row.updated_at = utcnow()
            session.merge(UserPreference(user_id=self.principal.user_id, project_id=target_id))
            self.audit(session, "group.reused", copied.id)
            return target, target_row.revision

    def audit(self, session: Session, action: str, entity_id: str) -> None:
        session.add(
            AuditEvent(
                organization_id=self.principal.organization_id,
                actor_id=self.principal.user_id,
                action=action,
                entity_id=entity_id,
            )
        )
