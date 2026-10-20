from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from escala_analyzer.api.factory import create_app
from escala_analyzer.cli import Administration
from escala_analyzer.infrastructure.database.connection import Database
from escala_analyzer.infrastructure.database.models import Base
from escala_analyzer.settings import Settings

PASSWORD = "test-account-password-2026"


@dataclass
class SaaSContext:
    database: Database
    settings: Settings
    client: TestClient
    admin_id: str

    def login(self, email: str = "admin@example.com", password: str = PASSWORD) -> dict[str, str]:
        response = self.client.post("/api/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.text
        self.client.headers["X-CSRF-Token"] = self.client.cookies["escala_csrf"]
        return self.client.get("/api/auth/me").json()


@pytest.fixture
def saas(tmp_path):
    settings = Settings(
        _env_file=None,
        environment="test",
        public_origin="https://testserver",
        database_url=f"sqlite:///{tmp_path}/saas.db",
        allowed_hosts=["testserver"],
        secure_cookies=True,
    )
    database = Database(settings.database_url)
    Base.metadata.create_all(database.engine)
    admin_id = Administration(database).provision(
        "Empresa A", "admin@example.com", "Admin", PASSWORD
    )
    app = create_app(settings, database)
    with TestClient(
        app, base_url="https://testserver", headers={"Origin": settings.public_origin}
    ) as client:
        yield SaaSContext(database, settings, client, admin_id)
