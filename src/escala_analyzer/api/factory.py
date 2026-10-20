"""SaaS composition root. No legacy routes or shared JSON repository are mounted."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from kombu import Connection
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from escala_analyzer.api import auth, jobs, projects, users
from escala_analyzer.api.middleware import RequestSafetyMiddleware
from escala_analyzer.application.services.errors import (
    CapacityError,
    ConflictError,
    NotFoundError,
    PreconditionError,
)
from escala_analyzer.infrastructure.database.connection import Database
from escala_analyzer.infrastructure.database.job_repository import JobRepository
from escala_analyzer.infrastructure.observability.logging import configure_logging
from escala_analyzer.infrastructure.security.authentication import Authentication
from escala_analyzer.settings import Settings

WEB = Path(__file__).parents[1] / "web"
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    configure_logging()
    settings = settings or Settings()
    database = database or Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        database.engine.dispose()

    app = FastAPI(
        title="Escala Visual SaaS",
        version="0.2.0rc1",
        lifespan=lifespan,
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.environment == "production" else "/openapi.json",
    )
    app.state.settings, app.state.database = settings, database
    app.state.authentication = Authentication(database, settings)
    app.state.jobs = JobRepository(database, settings)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        RequestSafetyMiddleware,
        max_body_bytes=settings.max_body_bytes,
        production=settings.environment == "production",
    )
    for router in (auth.router, users.router, projects.router, jobs.router):
        app.include_router(router)
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/", include_in_schema=False)
    def editor() -> FileResponse:
        return FileResponse(WEB / "index.html")

    @app.get("/login", include_in_schema=False)
    def login() -> FileResponse:
        return FileResponse(WEB / "login.html")

    @app.get("/account", include_in_schema=False)
    def account() -> FileResponse:
        return FileResponse(WEB / "account.html")

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "mode": "saas",
            "version": "0.2.0rc1",
            "rules_version": settings.rules_version,
        }

    @app.get("/health/live")
    def live() -> dict:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        try:
            with database.engine.connect() as connection:
                revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
                if revision != "0001_saas":
                    raise RuntimeError("schema_not_current")
            with Connection(settings.broker_url, connect_timeout=2) as broker:
                broker.ensure_connection(max_retries=0)
        except Exception:  # noqa: BLE001 — fault boundary records a safe status for retry/operations.
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Never reflect passwords, tokens or full snapshots in a validation response.
        errors = [
            {"loc": item["loc"], "msg": item["msg"], "type": item["type"]} for item in exc.errors()
        ]
        return JSONResponse(
            {"detail": errors, "request_id": request.state.request_id}, status_code=422
        )

    @app.exception_handler(NotFoundError)
    async def not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return failure(request, 404, str(exc))

    @app.exception_handler(ConflictError)
    async def conflict(request: Request, exc: ConflictError) -> JSONResponse:
        return failure(request, 409, str(exc))

    @app.exception_handler(PreconditionError)
    async def stale_revision(request: Request, exc: PreconditionError) -> JSONResponse:
        return failure(request, 412, str(exc))

    @app.exception_handler(CapacityError)
    async def capacity(request: Request, exc: CapacityError) -> JSONResponse:
        return failure(request, 429, str(exc))

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError) -> JSONResponse:
        return failure(request, 422, str(exc))

    @app.exception_handler(SQLAlchemyError)
    async def storage_failure(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error(
            "database_failure request_id=%s type=%s", request.state.request_id, type(exc).__name__
        )
        return failure(request, 503, "Persistência temporariamente indisponível.")

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unexpected_failure request_id=%s type=%s", request.state.request_id, type(exc).__name__
        )
        return failure(
            request, 500, "Falha interna. Informe o identificador da requisição ao suporte."
        )

    return app


def failure(request: Request, status: int, detail: str) -> JSONResponse:
    return JSONResponse(
        {"detail": detail, "request_id": request.state.request_id},
        status_code=status,
        headers={"X-Request-ID": request.state.request_id, "Cache-Control": "no-store"}
        if status == 500
        else {},
    )
