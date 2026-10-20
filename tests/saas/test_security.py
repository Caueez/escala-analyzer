from datetime import timedelta

import pytest
from conftest import PASSWORD
from sqlalchemy import select

from escala_analyzer.cli import Administration
from escala_analyzer.infrastructure.database.models import LoginSession, User, utcnow
from escala_analyzer.settings import Settings


def test_all_data_routes_require_authentication(saas):
    for path in ("/api/project", "/api/projects", "/api/users", "/api/jobs/nonexistent/result"):
        assert saas.client.get(path).status_code == 401
    assert saas.client.get("/api/health").json()["mode"] == "saas"


def test_login_cookie_flags_csrf_logout_and_no_password_disclosure(saas):
    response = saas.client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    cookies = response.headers.get_list("set-cookie")
    assert any(
        "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        for cookie in cookies
    )
    assert saas.client.post("/api/auth/logout").status_code == 403
    saas.client.headers["X-CSRF-Token"] = saas.client.cookies["escala_csrf"]
    assert "password" not in saas.client.get("/api/auth/me").text
    assert saas.client.post("/api/auth/logout").status_code == 200
    assert saas.client.get("/api/project").status_code == 401


def test_cross_origin_login_and_mutation_are_rejected(saas):
    assert (
        saas.client.post(
            "/api/auth/login",
            headers={"Origin": "https://attacker.example"},
            json={"email": "admin@example.com", "password": PASSWORD},
        ).status_code
        == 403
    )
    saas.login()
    assert (
        saas.client.post(
            "/api/auth/logout", headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )


def test_login_rate_limit_is_persisted(saas):
    for _ in range(8):
        assert (
            saas.client.post(
                "/api/auth/login", json={"email": "absent@example.com", "password": "incorrect"}
            ).status_code
            == 401
        )
    assert (
        saas.client.post(
            "/api/auth/login", json={"email": "absent@example.com", "password": "incorrect"}
        ).status_code
        == 429
    )


def test_session_idle_expiry_and_stored_tokens_are_hashes(saas):
    saas.login()
    token = saas.client.cookies["escala_session"]
    with saas.database.sessions.begin() as session:
        record = session.scalar(select(LoginSession))
        assert record.id != token
        record.last_seen_at = utcnow() - timedelta(minutes=61)
    assert saas.client.get("/api/project").status_code == 401


def test_password_change_revokes_sessions(saas):
    saas.login()
    assert (
        saas.client.post(
            "/api/auth/password",
            json={"current_password": PASSWORD, "new_password": "a-new-strong-password-2026"},
        ).status_code
        == 200
    )
    assert saas.client.get("/api/project").status_code == 401
    assert (
        saas.client.post(
            "/api/auth/login", json={"email": "admin@example.com", "password": PASSWORD}
        ).status_code
        == 401
    )
    saas.login(password="a-new-strong-password-2026")


def test_last_admin_cannot_be_deactivated_and_roles_are_enforced(saas):
    admin = saas.login()
    assert (
        saas.client.patch(
            "/api/users/" + admin["id"], json={"role": "viewer", "active": False}
        ).status_code
        == 409
    )
    response = saas.client.post(
        "/api/users",
        json={
            "email": "reader@example.com",
            "name": "Leitura",
            "password": PASSWORD,
            "role": "viewer",
        },
    )
    assert response.status_code == 201, response.text
    saas.login("reader@example.com")
    project = saas.client.get("/api/project").json()
    assert (
        saas.client.put("/api/project", json=project, headers={"If-Match": "1"}).status_code == 403
    )
    assert saas.client.get("/api/users").status_code == 403


def test_deactivated_user_session_stops_working(saas):
    saas.login()
    with saas.database.sessions.begin() as session:
        user = session.get(User, saas.admin_id)
        user.active = False
    assert saas.client.get("/api/project").status_code == 401


def test_production_config_rejects_insecure_modes():
    with pytest.raises(ValueError):
        Settings(_env_file=None, environment="production", mode="local")
    with pytest.raises(ValueError):
        Settings(_env_file=None, environment="production", database_url="sqlite:///unsafe.db")


def test_request_limits_security_headers_and_tenant_isolation(saas):
    saas.login()
    own = saas.client.get("/api/project")
    assert own.headers["cache-control"] == "no-store"
    assert own.headers["x-content-type-options"] == "nosniff"
    own_id = own.json()["project_id"]
    Administration(saas.database).provision("Empresa B", "other@example.com", "Other", PASSWORD)
    saas.login("other@example.com")
    assert saas.client.get("/api/projects/" + own_id).status_code == 404
    assert own_id not in {p["project_id"] for p in saas.client.get("/api/projects").json()}
    assert (
        saas.client.post(
            "/api/analyze", content="x" * (saas.settings.max_body_bytes + 1)
        ).status_code
        == 413
    )


def test_validation_errors_never_reflect_password_inputs(saas):
    saas.login()
    password = "private!"
    response = saas.client.post(
        "/api/users",
        json={"email": "new@example.com", "name": "New", "password": password, "role": "editor"},
    )
    assert response.status_code == 422
    assert password not in response.text
    assert "input" not in response.json()["detail"][0]
    assert response.headers["x-request-id"]


def test_database_timestamp_offsets_are_converted_not_relabelled():
    from datetime import datetime, timezone

    from escala_analyzer.infrastructure.database.models import timestamp_utc

    value = datetime(2026, 10, 20, 12, tzinfo=timezone(timedelta(hours=-3)))
    assert timestamp_utc(value).hour == 15
    assert timestamp_utc(datetime(2026, 10, 20, 15)).hour == 15
