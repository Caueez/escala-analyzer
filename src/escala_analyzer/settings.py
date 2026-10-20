"""Validated deployment settings. Production refuses insecure local fallbacks."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from escala_analyzer.domain.rules.version import RULE_ENGINE_VERSION


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ESCALA_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    mode: Literal["saas", "local"] = "saas"
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = Field(default="sqlite:///./data/escala.db", repr=False)
    broker_url: str = Field(default="amqp://guest:guest@localhost:5672//", repr=False)
    public_origin: str = "http://localhost:8000"
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    secure_cookies: bool = True
    session_hours: int = Field(default=8, ge=1, le=24)
    session_idle_minutes: int = Field(default=60, ge=5, le=120)
    max_body_bytes: int = Field(default=2_000_000, ge=1024, le=10_000_000)
    max_active_jobs: int = Field(default=4, ge=1, le=20)
    job_lease_seconds: int = Field(default=240, ge=210, le=900)
    job_retention_days: int = Field(default=7, ge=1, le=90)

    @property
    def rules_version(self) -> str:
        return RULE_ENGINE_VERSION

    @model_validator(mode="after")
    def production_requirements(self) -> "Settings":
        origin = urlsplit(self.public_origin)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.path not in {"", "/"}
            or origin.query
            or origin.fragment
        ):
            raise ValueError("PUBLIC_ORIGIN deve conter somente esquema e host.")
        if self.environment == "production":
            if self.mode != "saas" or not self.secure_cookies or origin.scheme != "https":
                raise ValueError("Produção exige SaaS, HTTPS e cookies Secure.")
            if not self.database_url.startswith("postgresql+psycopg://"):
                raise ValueError("Produção exige PostgreSQL com psycopg.")
            for url in (self.database_url, self.broker_url):
                parsed = urlsplit(url)
                if not parsed.password or len(parsed.password) < 32 or parsed.username == "guest":
                    raise ValueError(
                        "Banco e broker exigem credenciais próprias com 32+ caracteres."
                    )
            if "*" in self.allowed_hosts:
                raise ValueError("Produção exige hosts explícitos.")
        return self
