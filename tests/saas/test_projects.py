from uuid import uuid4


def test_revision_guard_rejects_stale_saves_and_missing_preconditions(saas):
    saas.login()
    current = saas.client.get("/api/project")
    project, revision = current.json(), current.headers["etag"]
    assert saas.client.put("/api/project", json=project).status_code == 428
    project["name"] = "Saved once"
    result = saas.client.put("/api/project", json=project, headers={"If-Match": revision})
    assert result.status_code == 200, result.text
    project["name"] = "Obsolete write"
    assert (
        saas.client.put("/api/project", json=project, headers={"If-Match": revision}).status_code
        == 412
    )
    assert saas.client.get("/api/project").json()["name"] == "Saved once"


def test_import_is_additive_and_never_overwrites_source_ids(saas):
    saas.login()
    current = saas.client.get("/api/project").json()
    current["name"] = "Imported copy"
    result = saas.client.post(
        "/api/projects/import",
        json={"schema_version": 2, "active_id": current["project_id"], "projects": [current]},
    )
    assert result.status_code == 200, result.text
    assert result.json()["project_id"] != current["project_id"]
    assert len(saas.client.get("/api/projects").json()) == 2


def test_project_creation_deletion_and_last_project_guard(saas):
    saas.login()
    first = saas.client.get("/api/project").json()
    second = {**first, "project_id": str(uuid4()), "name": "Second"}
    response = saas.client.put("/api/project", json=second, headers={"If-Match": "0"})
    assert response.status_code == 200, response.text
    assert (
        saas.client.delete(
            "/api/projects/" + second["project_id"], headers={"If-Match": response.headers["etag"]}
        ).status_code
        == 200
    )
    assert (
        saas.client.delete(
            "/api/projects/" + first["project_id"], headers={"If-Match": "1"}
        ).status_code
        == 422
    )


def test_linked_groups_propagate_atomically_and_invalidate_other_revisions(saas):
    saas.login()
    initial = saas.client.get("/api/project")
    source = initial.json()
    source["shifts"] = [
        {"id": "day", "name": "Dia", "hours_per_day": 8, "demand_by_weekday": [1] * 7}
    ]
    source["groups"] = [{"id": "g", "name": "Original", "shift_id": "day", "employee_count": 1}]
    saved = saas.client.put(
        "/api/project", json=source, headers={"If-Match": initial.headers["etag"]}
    )
    assert saved.status_code == 200, saved.text
    source = saved.json()
    target = {**source, "project_id": str(uuid4()), "groups": [], "name": "Target"}
    created = saas.client.put("/api/project", json=target, headers={"If-Match": "0"})
    assert created.status_code == 200, created.text
    reused = saas.client.post(
        "/api/projects/" + target["project_id"] + "/reuse-group",
        json={"source_project_id": source["project_id"], "group_id": "g", "linked": True},
        headers={"If-Match": created.headers["etag"]},
    )
    assert reused.status_code == 200, reused.text
    source_response = saas.client.get("/api/projects/" + source["project_id"])
    changed = source_response.json()
    changed["groups"][0]["name"] = "Changed by link"
    response = saas.client.put(
        "/api/project", json=changed, headers={"If-Match": source_response.headers["etag"]}
    )
    assert response.status_code == 200, response.text
    latest_target = saas.client.get("/api/projects/" + target["project_id"])
    assert latest_target.json()["groups"][0]["name"] == "Changed by link"
    assert (
        saas.client.put(
            "/api/project", json=reused.json(), headers={"If-Match": reused.headers["etag"]}
        ).status_code
        == 412
    )


def test_import_cannot_bypass_the_organization_project_limit(saas):
    saas.login()
    current = saas.client.get("/api/project").json()
    projects = [{**current, "project_id": str(uuid4())} for _ in range(100)]
    response = saas.client.post(
        "/api/projects/import",
        json={"schema_version": 2, "active_id": projects[0]["project_id"], "projects": projects},
    )
    assert response.status_code == 422
    assert len(saas.client.get("/api/projects").json()) == 1
