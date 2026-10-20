from datetime import time

from fastapi.testclient import TestClient

from escala_analyzer.container import ApplicationContainer
from escala_analyzer.domain.entities import ProjectState, RuleSettings, ScheduleGroup, Shift
from escala_analyzer.infrastructure.json_repository import JsonProjectRepository
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec
from escala_analyzer.presentation import local as main


def test_optimization_returns_valid_proposal_without_persisting(tmp_path, monkeypatch):
    repository = JsonProjectRepository(tmp_path / "project.json")
    project = ProjectState(
        year=2028,
        name="Busca teste",
        shifts=[
            Shift(
                id="day",
                name="Dia",
                start_time=time(8),
                break_minutes=60,
                demand_by_weekday=[2] * 7,
            )
        ],
        rules=RuleSettings(
            weekly_max_hours=40,
            min_rest_days_in_rolling_7=2,
            min_sundays_off_per_month=0,
            min_days_off_per_month=8,
            check_intershift_rest=True,
            check_breaks=True,
        ),
    )
    repository.save(project)
    original_bytes = repository.path.read_bytes()
    monkeypatch.setattr(main, "container", ApplicationContainer(repository=repository))
    with TestClient(main.app) as client:
        response = client.post(
            "/api/optimize",
            json={
                "project": EntityCodec.dump(project, mode="json"),
                "options": {
                    "cycles": [{"work_days": 1, "rest_days": 1}],
                    "max_group_size": 2,
                    "max_employees": 4,
                    "max_groups": 2,
                    "time_limit_seconds": 5,
                    "max_solutions": 4,
                },
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["solutions"]
        assert any(solution["baseline"] for solution in result["solutions"])
        assert result["metrics"]["group_count"] == 2
        assert result["metrics"]["people_total"] == 4
        assert result["metrics"]["surplus_staff_days"] == 0
        assert result["metrics"]["deficit_staff_days"] == 0
        assert repository.path.read_bytes() == original_bytes
        proposal = result["project"]
        analysis = client.post("/api/analyze", json=proposal).json()
        assert analysis["coverage_gap_count"] == 0
        assert analysis["rule_issue_count"] == 0
        assert proposal["project_id"] == project.project_id
        assert result["warnings"] == []


def test_optimization_rejects_unbounded_or_invalid_options(tmp_path, monkeypatch):
    monkeypatch.setattr(
        main,
        "container",
        ApplicationContainer(repository=JsonProjectRepository(tmp_path / "project.json")),
    )
    with TestClient(main.app) as client:
        project = EntityCodec.dump(ProjectState(), mode="json")
        for options in [
            {"max_group_size": 0},
            {"cycles": []},
            {"max_groups": -1},
            {"time_limit_seconds": 61},
            {"max_solutions": 0},
            {"max_solutions": 31},
            {"cycles": [{"work_days": 0, "rest_days": 1}]},
        ]:
            assert (
                client.post(
                    "/api/optimize", json={"project": project, "options": options}
                ).status_code
                == 422
            )


def test_ranked_partial_proposals_keep_existing_groups_and_are_not_saved(tmp_path, monkeypatch):
    repository = JsonProjectRepository(tmp_path / "project.json")
    existing = ScheduleGroup(
        id="original",
        name="Equipe original",
        shift_id="day",
        employee_count=1,
        work_days=6,
        rest_days=1,
        overrides={"2026-01-05": False},
        layer_by_shift={"day": 7},
    )
    project = ProjectState(
        year=2026,
        shifts=[
            Shift(
                id="day",
                name="Dia",
                hours_per_day=8,
                start_time=time(8),
                break_minutes=0,
                demand_by_weekday=[3] * 7,
            )
        ],
        groups=[existing],
        rules=RuleSettings(check_breaks=True),
    )
    repository.save(project)
    before = repository.path.read_bytes()
    monkeypatch.setattr(main, "container", ApplicationContainer(repository=repository))
    with TestClient(main.app) as client:
        response = client.post(
            "/api/optimize",
            json={
                "project": EntityCodec.dump(project, mode="json"),
                "options": {
                    "cycles": [{"work_days": 1, "rest_days": 1}],
                    "max_groups": 3,
                    "max_employees": 6,
                    "time_limit_seconds": 5,
                    "max_solutions": 4,
                },
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert len(result["solutions"]) >= 2
        ranks = [solution["ranking"] for solution in result["solutions"]]
        assert ranks == sorted(ranks)
        for solution in result["solutions"]:
            originals = [
                group for group in solution["project"]["groups"] if group["id"] == existing.id
            ]
            assert originals == [EntityCodec.dump(existing, mode="json")]
            assert solution["issues"]  # Existing interval/rest violations remain visible.
            validation = client.post("/api/analyze", json=solution["project"]).json()
            assert validation["rule_issue_count"] > 0
        assert repository.path.read_bytes() == before
