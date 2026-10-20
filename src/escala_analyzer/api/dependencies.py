"""Authentication, CSRF and role checks are shared by every protected route."""

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from escala_analyzer.application.services.identity import Principal
from escala_analyzer.infrastructure.database.project_repository import SqlProjectRepository
from escala_analyzer.infrastructure.security.passwords import Passwords


class Access:
    @staticmethod
    def current(request: Request) -> Principal:
        principal = request.app.state.authentication.resolve(request.cookies.get("escala_session"))
        if not principal:
            raise HTTPException(401, "Autenticação necessária.")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            supplied = request.headers.get("X-CSRF-Token", "")
            if not supplied or not hmac.compare_digest(
                Passwords.digest(supplied), principal.csrf_hash
            ):
                raise HTTPException(403, "Token CSRF inválido.")
            Access.origin(request)
        return principal

    @staticmethod
    def origin(request: Request) -> None:
        if request.headers.get("origin", "").rstrip(
            "/"
        ) != request.app.state.settings.public_origin.rstrip("/"):
            raise HTTPException(403, "Origem não autorizada.")

    @staticmethod
    def editor(principal: Annotated[Principal, Depends(current)]) -> Principal:
        if not principal.can_edit:
            raise HTTPException(403, "Permissão de edição necessária.")
        return principal

    @staticmethod
    def admin(principal: Annotated[Principal, Depends(current)]) -> Principal:
        if principal.role != "admin":
            raise HTTPException(403, "Permissão de administrador necessária.")
        return principal

    @staticmethod
    def repository(
        request: Request, principal: Annotated[Principal, Depends(current)]
    ) -> SqlProjectRepository:
        return SqlProjectRepository(request.app.state.database, principal)

    @staticmethod
    def revision(request: Request) -> int:
        value = request.headers.get("If-Match")
        if value is None:
            raise HTTPException(428, "Informe a revisão em If-Match; 0 para um novo projeto.")
        try:
            revision = int(value.strip('"'))
            if revision < 0:
                raise ValueError
            return revision
        except ValueError as exc:
            raise HTTPException(400, "Revisão inválida.") from exc
