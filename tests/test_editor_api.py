from datetime import date, time

from fastapi.testclient import TestClient

from escala_analyzer.container import ApplicationContainer
from escala_analyzer.domain.entities import ProjectState, ScheduleGroup, Shift
from escala_analyzer.infrastructure.json_repository import JsonProjectRepository
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec
from escala_analyzer.presentation import local as main


def test_editor_migrates_legacy_backup_without_planning_or_costs():
    project = EntityCodec.load(
        ProjectState,
        {
            "name": "Backup",
            "planning": {"allow_rotation": False},
            "shifts": [
                {
                    "id": "s",
                    "name": "Dia",
                    "monthly_employee_cost": 2000,
                    "overtime_hour_cost": 50,
                    "journey_id": "legacy",
                }
            ],
            "groups": [
                {
                    "id": "g",
                    "name": "Equipe",
                    "allocations": {"s": 2},
                    "rotation_shift_ids": ["s"],
                    "employee_count": 2,
                }
            ],
        },
    )
    raw = EntityCodec.dump(project, mode="json")
    assert "planning" not in raw
    assert "monthly_employee_cost" not in raw["shifts"][0]
    assert "overtime_hour_cost" not in raw["shifts"][0]
    assert project.groups[0].rotation_shift_ids == ["s"]


def test_editor_api_saves_reload_and_has_no_planner(tmp_path, monkeypatch):
    repository = JsonProjectRepository(tmp_path / "project.json")
    monkeypatch.setattr(main, "container", ApplicationContainer(repository=repository))
    with TestClient(main.app) as client:
        project = ProjectState(
            name="Minha escala",
            year=2028,
            shifts=[
                Shift(id="s", name="Noite", start_time=time(22), hours_per_day=8, break_minutes=60)
            ],
            groups=[ScheduleGroup(id="g", name="G", shift_id="s", cycle_anchor=date(2028, 1, 1))],
        )
        payload = EntityCodec.dump(project, mode="json")
        assert client.put("/api/project", json=payload).status_code == 200
        assert client.get("/api/project").json() == payload
        result = client.post("/api/analyze", json=payload)
        assert result.status_code == 200
        assert result.json()["days_in_year"] == 366
        assert client.post("/api/plan", json=payload).status_code == 404
        assert JsonProjectRepository(tmp_path / "project.json").load() == project
