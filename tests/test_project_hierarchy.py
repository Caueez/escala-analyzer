from fastapi.testclient import TestClient

from escala_analyzer.container import ApplicationContainer
from escala_analyzer.domain.entities import ProjectState, ScheduleGroup, Shift
from escala_analyzer.infrastructure.json_repository import JsonProjectRepository
from escala_analyzer.infrastructure.optimization.schedule_optimizer import OptimizationOptions
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec
from escala_analyzer.presentation import local as main


def test_automatic_cycles_include_simple_composite_and_no_repeated_periods():
    cycles = OptimizationOptions(automatic_cycles=True, max_cycle_days=7).candidate_cycles()
    blocks = [tuple(c.blocks) for c in cycles]
    assert (5, 2) in blocks
    assert any(len(b) > 2 for b in blocks)
    assert (1, 1, 1, 1) not in blocks
    assert all(sum(b) <= 7 for b in blocks)


def test_legacy_projects_become_subdivisions_of_same_portfolio(tmp_path):
    repo = JsonProjectRepository(tmp_path / "project.json")
    first = repo.load()
    second = ProjectState(name="Outra escala")
    repo.save(second)
    assert {p.portfolio_id for p in repo.list_projects()} == {"legacy"}
    assert {p.portfolio_name for p in repo.list_projects()} == {"Fiação 2027"}
    second.portfolio_name = "Fiação revisada"
    repo.save(second)
    assert repo.load_by_id(first.project_id).portfolio_name == "Fiação revisada"


def test_reuse_link_copy_unlink_and_restart(tmp_path, monkeypatch):
    repo = JsonProjectRepository(tmp_path / "project.json")
    source = ProjectState(
        shifts=[Shift(id="s", name="Dia")],
        groups=[ScheduleGroup(id="g", name="Equipe", shift_id="s")],
    )
    target = ProjectState(portfolio_id="other", portfolio_name="Outro projeto")
    repo.save(source)
    repo.save(target)
    monkeypatch.setattr(main, "container", ApplicationContainer(repository=repo))
    with TestClient(main.app) as client:
        url = f"/api/projects/{target.project_id}/reuse-group"
        payload = {"source_project_id": source.project_id, "group_id": "g", "linked": True}
        response = client.post(url, json=payload)
        assert response.status_code == 200, response.text
        linked = EntityCodec.load(ProjectState, response.json())
        assert len(linked.shifts) == 1
        assert linked.groups[0].id != "g"
        linked.groups[0].name = "Compartilhada"
        assert (
            client.put("/api/project", json=EntityCodec.dump(linked, mode="json")).status_code
            == 200
        )
        assert repo.load_by_id(source.project_id).groups[0].name == "Compartilhada"
        payload["linked"] = False
        assert client.post(url, json=payload).status_code == 200
        current = repo.load_by_id(target.project_id)
        current.shared_group_links.clear()
        current.groups[0].name = "Independente"
        repo.save(current)
        restored = JsonProjectRepository(repo.path)
        assert restored.load_by_id(source.project_id).groups[0].name == "Compartilhada"
        assert restored.load_by_id(target.project_id).groups[1].name == "Compartilhada"


def test_reuse_shift_conflict_does_not_modify_source(tmp_path, monkeypatch):
    repo = JsonProjectRepository(tmp_path / "project.json")
    source = ProjectState(
        shifts=[Shift(id="s", name="Dia")],
        groups=[ScheduleGroup(id="g", name="Equipe", shift_id="s")],
    )
    target = ProjectState(shifts=[Shift(id="s", name="Noite")])
    repo.save(source)
    repo.save(target)
    monkeypatch.setattr(main, "container", ApplicationContainer(repository=repo))
    before = repo.path.read_bytes()
    with TestClient(main.app) as client:
        response = client.post(
            f"/api/projects/{target.project_id}/reuse-group",
            json={"source_project_id": source.project_id, "group_id": "g", "linked": True},
        )
        assert response.status_code == 422
    assert repo.path.read_bytes() == before


def test_import_backup_restores_all_subdivisions_atomically(tmp_path, monkeypatch):
    repo = JsonProjectRepository(tmp_path / "project.json")
    preserved = repo.load()
    a, b = ProjectState(name="A"), ProjectState(name="B")
    monkeypatch.setattr(main, "container", ApplicationContainer(repository=repo))
    with TestClient(main.app) as client:
        body = {
            "schema_version": 2,
            "active_id": b.project_id,
            "projects": [EntityCodec.dump(a, mode="json"), EntityCodec.dump(b, mode="json")],
        }
        response = client.post("/api/projects/import", json=body)
        assert response.status_code == 200
        assert repo.load().project_id == b.project_id
        assert {p.project_id for p in repo.list_projects()} == {
            preserved.project_id,
            a.project_id,
            b.project_id,
        }
        before = repo.path.read_bytes()
        body["projects"][1]["groups"] = [{"id": "bad", "name": "Bad", "shift_id": "missing"}]
        assert client.post("/api/projects/import", json=body).status_code == 422
        assert repo.path.read_bytes() == before


def test_editing_one_occurrence_updates_all_local_linked_occurrences(tmp_path):
    repo = JsonProjectRepository(tmp_path / "project.json")
    project = ProjectState(
        shifts=[Shift(id="s", name="Dia")],
        groups=[
            ScheduleGroup(id="a", name="Equipe", shift_id="s"),
            ScheduleGroup(id="b", name="Equipe", shift_id="s"),
        ],
        shared_group_links={"a": "shared", "b": "shared"},
    )
    repo.save(project)
    project.groups[0].name = "Alterada"
    repo.save(project)
    assert [g.name for g in project.groups] == ["Alterada", "Alterada"]
    assert [g.name for g in repo.load().groups] == ["Alterada", "Alterada"]
