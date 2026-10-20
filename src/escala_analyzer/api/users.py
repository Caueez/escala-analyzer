"""Tenant administrators manage users; credentials never appear in responses."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from escala_analyzer.api.dependencies import Access
from escala_analyzer.application.services.identity import Principal, Role
from escala_analyzer.infrastructure.database.models import (
    AuditEvent,
    LoginSession,
    Organization,
    User,
)

router = APIRouter(prefix="/api/users", tags=["users"])


class CreateUserInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=128)
    role: Role = "editor"

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Informe um nome válido.")
        return value.strip()


class ChangeUserInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role
    active: bool


@router.get("")
def list_users(
    request: Request, principal: Annotated[Principal, Depends(Access.admin)]
) -> list[dict]:
    with request.app.state.database.sessions() as session:
        return [
            view(user)
            for user in session.scalars(
                select(User)
                .where(User.organization_id == principal.organization_id)
                .order_by(User.created_at)
            )
        ]


@router.post("", status_code=201)
def create_user(
    payload: CreateUserInput,
    request: Request,
    principal: Annotated[Principal, Depends(Access.admin)],
) -> dict:
    try:
        with request.app.state.database.sessions.begin() as session:
            session.scalar(
                select(Organization)
                .where(Organization.id == principal.organization_id)
                .with_for_update()
            )
            count = (
                session.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.organization_id == principal.organization_id)
                )
                or 0
            )
            if count >= 100:
                raise HTTPException(409, "Limite de 100 usuários por empresa atingido.")
            user = User(
                organization_id=principal.organization_id,
                email=str(payload.email).casefold(),
                name=payload.name.strip(),
                role=payload.role,
                password_hash=request.app.state.authentication.passwords.hash(payload.password),
            )
            session.add(user)
            session.flush()
            session.add(
                AuditEvent(
                    organization_id=principal.organization_id,
                    actor_id=principal.user_id,
                    action="user.created",
                    entity_id=user.id,
                )
            )
            return view(user)
    except IntegrityError as exc:
        raise HTTPException(409, "Não foi possível cadastrar esse email.") from exc


@router.patch("/{user_id}")
def change_user(
    user_id: str,
    payload: ChangeUserInput,
    request: Request,
    principal: Annotated[Principal, Depends(Access.admin)],
) -> dict:
    with request.app.state.database.sessions.begin() as session:
        session.scalar(
            select(Organization)
            .where(Organization.id == principal.organization_id)
            .with_for_update()
        )
        user = session.scalar(
            select(User).where(
                User.id == user_id, User.organization_id == principal.organization_id
            )
        )
        if not user:
            raise HTTPException(404, "Usuário não encontrado.")
        if user.role == "admin" and user.active and (payload.role != "admin" or not payload.active):
            admins = (
                session.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(
                        User.organization_id == principal.organization_id,
                        User.active.is_(True),
                        User.role == "admin",
                    )
                )
                or 0
            )
            if admins <= 1:
                raise HTTPException(409, "Mantenha ao menos um administrador ativo.")
        user.role, user.active = payload.role, payload.active
        session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
        session.add(
            AuditEvent(
                organization_id=principal.organization_id,
                actor_id=principal.user_id,
                action="user.changed",
                entity_id=user.id,
            )
        )
        return view(user)


def view(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "active": user.active,
    }
