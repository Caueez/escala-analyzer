"""Offline provisioning, password recovery, migration and retention commands."""

import argparse
import json
from getpass import getpass
from pathlib import Path

from sqlalchemy import delete, select

from escala_analyzer.application.services.identity import Principal
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.infrastructure.database.connection import Database
from escala_analyzer.infrastructure.database.models import (
    AuditEvent,
    LoginSession,
    Organization,
    Project,
    User,
    UserPreference,
)
from escala_analyzer.infrastructure.database.project_repository import SqlProjectRepository
from escala_analyzer.infrastructure.database.retention import Retention
from escala_analyzer.infrastructure.security.passwords import Passwords
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec
from escala_analyzer.settings import Settings


class Administration:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.passwords = Passwords()

    def provision(self, organization: str, email: str, name: str, password: str) -> str:
        from email_validator import validate_email

        email = validate_email(email, check_deliverability=False).normalized.casefold()
        organization, name = organization.strip(), name.strip()
        if not 1 <= len(organization) <= 160 or not 1 <= len(name) <= 120:
            raise ValueError("Informe empresa (até 160 caracteres) e nome (até 120 caracteres).")
        encoded = self.passwords.hash(password)
        with self.database.sessions.begin() as session:
            if session.scalar(select(User).where(User.email == email)):
                raise ValueError("Email já cadastrado.")
            tenant = Organization(name=organization)
            session.add(tenant)
            session.flush()
            user = User(
                organization_id=tenant.id,
                email=email,
                name=name,
                role="admin",
                password_hash=encoded,
            )
            session.add(user)
            session.flush()
            project = ProjectState(portfolio_name=organization)
            session.add(
                Project(
                    organization_id=tenant.id,
                    id=project.project_id,
                    payload=EntityCodec.dump(project, mode="json"),
                )
            )
            session.add(UserPreference(user_id=user.id, project_id=project.project_id))
            session.add(
                AuditEvent(
                    organization_id=tenant.id,
                    actor_id=user.id,
                    action="organization.provisioned",
                    entity_id=tenant.id,
                )
            )
            return user.id

    def reset_password(self, email: str, password: str) -> None:
        with self.database.sessions.begin() as session:
            user = session.scalar(select(User).where(User.email == email.strip().casefold()))
            if not user:
                raise ValueError("Usuário não encontrado.")
            user.password_hash = self.passwords.hash(password)
            session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
            session.add(
                AuditEvent(
                    organization_id=user.organization_id,
                    actor_id="operator",
                    action="auth.password_reset",
                    entity_id=user.id,
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Operação do Escala Visual")
    sub = parser.add_subparsers(dest="command", required=True)
    provision = sub.add_parser("provision")
    provision.add_argument("--organization", required=True)
    provision.add_argument("--email", required=True)
    provision.add_argument("--name", required=True)
    reset = sub.add_parser("reset-password")
    reset.add_argument("--email", required=True)
    legacy = sub.add_parser("import-json")
    legacy.add_argument("--email", required=True)
    legacy.add_argument("--file", type=Path, required=True)
    sub.add_parser("cleanup")
    args = parser.parse_args()
    settings = Settings()
    database = Database(settings.database_url)
    try:
        admin = Administration(database)
        if args.command in {"provision", "reset-password"}:
            password = getpass("Senha (12–128 caracteres): ")
            if password != getpass("Repita a senha: "):
                raise ValueError("Senhas diferentes.")
            if args.command == "provision":
                admin.provision(args.organization, args.email, args.name, password)
            else:
                admin.reset_password(args.email, password)
        elif args.command == "import-json":
            raw = json.loads(args.file.read_text())
            with database.sessions() as session:
                user = session.scalar(
                    select(User).where(
                        User.email == args.email.casefold(),
                        User.active.is_(True),
                        User.role == "admin",
                    )
                )
                if not user:
                    raise ValueError("Administrador não encontrado.")
                principal = Principal(user.id, user.organization_id, user.role, user.name, "", "")
            items = raw.get("projects", [raw])
            projects = [EntityCodec.load(ProjectState, item) for item in items]
            SqlProjectRepository(database, principal).import_projects(
                projects, raw.get("active_id", projects[0].project_id)
            )
        elif args.command == "cleanup":
            Retention.cleanup(database, settings.job_retention_days)
        print("Operação concluída.")
    finally:
        database.engine.dispose()


if __name__ == "__main__":
    main()
