"""Session endpoints; no public registration or browser-stored bearer tokens."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from escala_analyzer.api.dependencies import Access
from escala_analyzer.application.services.identity import Principal

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


@router.post("/login")
def login(payload: LoginInput, request: Request, response: Response) -> dict[str, str]:
    Access.origin(request)
    result = request.app.state.authentication.login(
        str(payload.email), payload.password, request.client.host if request.client else "unknown"
    )
    if result == "rate_limited":
        raise HTTPException(
            429, "Muitas tentativas. Aguarde 15 minutos.", headers={"Retry-After": "900"}
        )
    if isinstance(result, str):
        raise HTTPException(401, "Email ou senha inválidos.")
    token, csrf = result
    options = {
        "secure": request.app.state.settings.secure_cookies,
        "samesite": "strict",
        "path": "/",
        "max_age": request.app.state.settings.session_hours * 3600,
    }
    response.set_cookie("escala_session", token, httponly=True, **options)
    response.set_cookie("escala_csrf", csrf, httponly=False, **options)
    return {"status": "authenticated"}


@router.get("/me")
def me(principal: Annotated[Principal, Depends(Access.current)]) -> dict[str, str]:
    return {
        "id": principal.user_id,
        "organization_id": principal.organization_id,
        "name": principal.name,
        "role": principal.role,
    }


@router.post("/logout")
def logout(
    request: Request, response: Response, principal: Annotated[Principal, Depends(Access.current)]
) -> dict[str, str]:
    request.app.state.authentication.logout(principal)
    response.delete_cookie(
        "escala_session",
        path="/",
        secure=request.app.state.settings.secure_cookies,
        samesite="strict",
    )
    response.delete_cookie(
        "escala_csrf", path="/", secure=request.app.state.settings.secure_cookies, samesite="strict"
    )
    return {"status": "logged_out"}


@router.post("/password")
def password(
    payload: PasswordInput,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(Access.current)],
) -> dict[str, str]:
    if not request.app.state.authentication.change_password(
        principal, payload.current_password, payload.new_password
    ):
        raise HTTPException(400, "Senha atual inválida.")
    response.delete_cookie("escala_session", path="/")
    response.delete_cookie("escala_csrf", path="/")
    return {"status": "sessions_revoked"}
