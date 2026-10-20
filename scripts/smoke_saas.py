"""Live release smoke test against an isolated Compose deployment on localhost.

The script provisions a new disposable company and exercises the real API/broker/workers.
Never point it at a customer environment. It deliberately accepts loopback URLs only.
"""

import argparse
import json
import os
import secrets
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--env-file", required=True)
parser.add_argument("--project", default="escala-candidate-check")
parser.add_argument("--url", default="http://localhost:18088")
parser.add_argument("--check-broker-restart", action="store_true")
args = parser.parse_args()
if urlsplit(args.url).hostname not in {"localhost", "127.0.0.1"}:
    parser.error("Only an isolated local deployment is accepted.")
os.environ["ESCALA_ENV_FILE"] = str(Path(args.env_file).resolve())
compose = ["docker", "compose", "--env-file", args.env_file, "-p", args.project]
password = secrets.token_urlsafe(24)
email = f"rc-{uuid4().hex[:12]}@example.com"
provision = f"""
from escala_analyzer.cli import Administration
from escala_analyzer.infrastructure.database.connection import Database
from escala_analyzer.settings import Settings
Administration(Database(Settings().database_url)).provision('Release check', {email!r}, 'Release Admin', {password!r})
"""
subprocess.run(
    [*compose, "exec", "-T", "app", "python", "-"], input=provision, text=True, check=True
)
privileges = """
import os
assert not any(key in os.environ for key in ("POSTGRES_PASSWORD", "ESCALA_MIGRATOR_PASSWORD", "ESCALA_MIGRATION_DATABASE_URL")), "administrative secrets leaked into runtime"
from sqlalchemy import text
from escala_analyzer.infrastructure.database.connection import Database
from escala_analyzer.settings import Settings
with Database(Settings().database_url).engine.connect() as connection:
    row = connection.execute(text("SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user")).one()
    assert not any(row), 'runtime database role is overprivileged'
    assert not connection.scalar(text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')"))
    assert not connection.scalar(text("SELECT has_table_privilege(current_user, 'alembic_version', 'UPDATE')"))
"""
subprocess.run(
    [*compose, "exec", "-T", "app", "python", "-"], input=privileges, text=True, check=True
)
client = httpx.Client(base_url=args.url, headers={"Origin": args.url}, timeout=15)
assert client.get("/health/ready").status_code == 200
assert client.get("/api/project").status_code == 401
response = client.post("/api/auth/login", json={"email": email, "password": password})
assert response.status_code == 200, response.text
client.headers["X-CSRF-Token"] = client.cookies["escala_csrf"]
original = client.get("/api/project")
project, revision = original.json(), original.headers["etag"]
project["name"] = "Release smoke"
project["shifts"] = [{"id": "day", "name": "Dia", "hours_per_day": 8, "demand_by_weekday": [1] * 7}]
response = client.put("/api/project", json=project, headers={"If-Match": revision})
assert response.status_code == 200, response.text
revision = response.headers["etag"]
assert (
    client.put(
        "/api/project", json=project, headers={"If-Match": original.headers["etag"]}
    ).status_code
    == 412
)


def wait_job(job):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        status = client.get(job["status_url"]).json()
        if status["state"] == "succeeded":
            return client.get(job["result_url"]).json()
        assert status["state"] not in {"failed", "cancelled"}, status
        time.sleep(0.5)
    raise AssertionError("worker did not finish before deadline")


key = str(uuid4())
job = client.post("/api/analyze", json=project, headers={"Idempotency-Key": key})
assert job.status_code == 202, job.text
assert (
    client.post("/api/analyze", json=project, headers={"Idempotency-Key": key}).json()["id"]
    == job.json()["id"]
)
analysis = wait_job(job.json())
assert analysis["days_in_year"] in {365, 366}
assert analysis["shift_count"] == 1
job = client.post(
    "/api/optimize",
    json={
        "project": project,
        "options": {
            "cycles": [{"work_days": 1, "rest_days": 1}],
            "time_limit_seconds": 2,
            "max_solutions": 2,
        },
    },
    headers={"Idempotency-Key": str(uuid4())},
)
assert job.status_code == 202, job.text
result = wait_job(job.json())
assert result["solutions"] and any(item["baseline"] for item in result["solutions"])
assert client.get("/api/project").json()["groups"] == []
export = client.post("/api/export", json=project, headers={"Idempotency-Key": str(uuid4())})
assert export.status_code == 202, export.text
csv = client.get(wait_job(export.json())["download_url"])
assert csv.status_code == 200 and "text/csv" in csv.headers["content-type"]
assert len(csv.text.splitlines()) > 365


def concurrent_write(name):
    with httpx.Client(
        base_url=args.url, headers=dict(client.headers), cookies=client.cookies, timeout=15
    ) as peer:
        return peer.put(
            "/api/project", json={**project, "name": name}, headers={"If-Match": revision}
        ).status_code


with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(concurrent_write, ["Concurrent A", "Concurrent B"]))
assert sorted(results) == [200, 412], results
if args.check_broker_restart:
    subprocess.run([*compose, "stop", "broker"], check=True, capture_output=True)
    try:
        delayed = client.post(
            "/api/analyze", json=project, headers={"Idempotency-Key": str(uuid4())}
        )
        assert delayed.status_code == 202, delayed.text
        assert client.get(delayed.json()["status_url"]).json()["state"] == "queued"
        assert client.get("/health/ready").status_code == 503
        time.sleep(3)
    finally:
        subprocess.run([*compose, "start", "broker"], check=True, capture_output=True)
    assert wait_job(delayed.json())["year"] == project["year"]

assert client.post("/api/auth/logout").status_code == 200
assert client.get("/api/project").status_code == 401
print(
    json.dumps(
        {
            "live_release_smoke": "passed",
            "broker_restart_verified": args.check_broker_restart,
            "checks": [
                "PostgreSQL persistence",
                "least-privilege runtime role",
                "login/CSRF/revocation",
                "concurrent If-Match",
                "durable idempotent analysis",
                "RabbitMQ analysis worker",
                "RabbitMQ optimization worker",
                "asynchronous CSV export",
                "no automatic proposal application",
            ],
        }
    )
)
