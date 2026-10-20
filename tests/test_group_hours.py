from dataclasses import replace
from datetime import date, time

import pytest

from escala_analyzer.domain.analysis.project_analyzer import ProjectAnalyzer
from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.entities import ProjectState, RuleSettings, ScheduleGroup, Shift
from escala_analyzer.infrastructure.optimization.group_hours_optimizer import GroupHoursOptimizer
from escala_analyzer.infrastructure.optimization.schedule_optimizer import (
    OptimizationCycle,
    OptimizationOptions,
    ScheduleOptimizer,
)
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec


def make_project():
    return ProjectState(
        year=2026,
        shifts=[
            Shift(
                id="s",
                name="Dia",
                hours_per_day=8,
                start_time=time(8),
                break_minutes=60,
                demand_by_weekday=[2] * 7,
            )
        ],
        groups=[
            ScheduleGroup(
                id="g",
                name="Equipe",
                shift_id="s",
                employee_count=3,
                work_days=6,
                rest_days=1,
                cycle_anchor=date(2026, 1, 1),
            )
        ],
        rules=RuleSettings(
            weekly_max_hours=40,
            min_rest_days_in_rolling_7=0,
            max_consecutive_work_days=31,
            check_min_days_off_per_month=False,
            min_sundays_off_per_month=0,
            check_breaks=True,
            check_intershift_rest=True,
        ),
    )


def test_weekday_hours_inherit_turn_or_override_net_work_and_end_time():
    p = make_project()
    g = p.groups[0]
    # Jan 1, 2026 is Thursday; Jan 2 is Friday, with its own duration.
    g.work_hours_by_weekday = [None, None, None, 6, 4, None, None]
    result = ProjectAnalyzer().analyze(p)
    journeys = result["group_annual"][0]["allocations"][0]["journeys"]
    assert journeys[0]["work_hours"] == 6
    assert journeys[0]["end"].endswith("15:00:00")
    assert journeys[1]["work_hours"] == 4
    assert journeys[1]["end"].endswith("13:00:00")
    assert journeys[2]["work_hours"] == 8
    assert result["group_annual"][0]["work_hours"] == sum(
        row["work_hours"] for row in result["group_monthly"]
    )


def test_zero_weekday_is_rest_even_when_manual_override_says_work():
    p = make_project()
    g = p.groups[0]
    g.work_hours_by_weekday[3] = 0
    g.overrides["2026-01-01"] = True
    assert not ScheduleCalendar.is_working(g, date(2026, 1, 1))
    result = ProjectAnalyzer().analyze(p)
    assert result["coverage_by_day"][0]["shifts"][0]["scheduled"] == 0
    assert not any(
        j["date"] == "2026-01-01" for j in result["group_annual"][0]["allocations"][0]["journeys"]
    )


def test_short_hours_do_not_hide_understaffed_work_hours():
    p = make_project()
    p.groups[0].work_hours_by_weekday = [4] * 7
    result = ProjectAnalyzer().analyze(p)
    row = result["coverage_by_day"][0]["shifts"][0]
    assert row["scheduled"] == 3
    assert row["deficit"] == 0
    assert row["scheduled_work_hours"] == 12
    assert row["required_work_hours"] == 16
    assert row["deficit_work_hours"] == 4
    assert any(i["code"] == "coverage-hours-gap" for i in result["coverage_issues"])


def test_weekday_hours_validation_and_backwards_compatibility():
    g = ScheduleGroup(id="g", name="G", shift_id="s")
    assert g.work_hours_by_weekday == [None] * 7
    for hours in ([8] * 6, [float("nan")] * 7, [25] * 7, [-1] * 7):
        with pytest.raises(ValueError):
            ScheduleGroup(id="g", name="G", work_hours_by_weekday=hours)
    with pytest.raises(ValueError):
        ScheduleGroup(id="g", name="G", min_hours_by_weekday=[9] * 7, max_hours_by_weekday=[8] * 7)
    p = make_project()
    p.groups[0].work_hours_by_weekday = [24] * 7
    with pytest.raises(ValueError):
        EntityCodec.load(ProjectState, EntityCodec.dump(p))


def test_hours_solver_fixes_weekly_cap_preserving_groups_coverage_and_metadata():
    p = make_project()
    p.groups[0].allow_hours_optimization = True
    p.groups[0].overrides = {"2026-01-04": False}
    snapshot = EntityCodec.dump_json(p)
    optimized, report = GroupHoursOptimizer().optimize(p, 15, 5)
    assert report["status"] == "optimized"
    assert report["groups"] == ["g"]
    assert EntityCodec.dump_json(p) == snapshot
    assert optimized.groups[0].id == "g"
    assert optimized.groups[0].allocations == p.groups[0].allocations
    assert optimized.groups[0].overrides == p.groups[0].overrides
    assert optimized.groups[0].cycle_anchor == p.groups[0].cycle_anchor
    assert all(
        6 <= h <= 8 and h * 4 == round(h * 4) for h in optimized.groups[0].work_hours_by_weekday
    )
    result = ProjectAnalyzer().analyze(optimized)
    assert not any(i["code"] == "rolling-hours" for i in result["rule_issues"])
    before = ProjectAnalyzer().analyze(p)
    assert sum(
        s["deficit_work_hours"] for d in result["coverage_by_day"] for s in d["shifts"]
    ) == sum(s["deficit_work_hours"] for d in before["coverage_by_day"] for s in d["shifts"])


def test_hours_solver_leaves_unpermitted_groups_untouched():
    p = make_project()
    adjusted, report = GroupHoursOptimizer().optimize(p, 15, 2)
    assert adjusted == p
    assert report["status"] == "unchanged"


def test_existing_hours_optimized_even_without_space_for_new_groups():
    p = make_project()
    p.groups[0].allow_hours_optimization = True
    result = ScheduleOptimizer().optimize(
        p,
        OptimizationOptions(
            optimize_work_hours=True,
            max_groups=1,
            max_employees=3,
            max_solutions=4,
            time_limit_seconds=8,
        ),
    )
    assert any(solution["baseline"] for solution in result["solutions"])
    changed = [s for s in result["solutions"] if s["hour_changes"]]
    assert changed
    assert any(s["metrics"]["rule_violation_count"] == 0 for s in changed)
    assert all(len(s["project"]["groups"]) == 1 for s in result["solutions"])
    assert p.groups[0].work_hours_by_weekday == [None] * 7


def test_group_optimization_requires_global_authorization_too():
    p = make_project()
    p.groups[0].allow_hours_optimization = True
    result = ScheduleOptimizer().optimize(
        p, OptimizationOptions(optimize_work_hours=False, max_groups=1)
    )
    assert len(result["solutions"]) == 1
    assert result["project"]["groups"][0]["work_hours_by_weekday"] == [None] * 7


def test_optimizer_adds_staff_for_missing_hours_even_when_headcount_is_sufficient():
    p = make_project()
    p.rules.weekly_max_hours = 168
    p.groups[0].work_hours_by_weekday = [4] * 7
    result = ScheduleOptimizer().optimize(
        p,
        OptimizationOptions(
            cycles=[OptimizationCycle(work_days=1, rest_days=1)],
            max_solutions=3,
            time_limit_seconds=5,
        ),
    )
    assert result["solutions"][0]["metrics"]["deficit_work_hours"] == 0
    assert result["solutions"][0]["metrics"]["added_group_count"] > 0


def test_daily_hour_bounds_are_visible_in_analysis():
    p = make_project()
    p.groups[0].allow_hours_optimization = True
    p.groups[0].work_hours_by_weekday = [9] * 7
    result = ProjectAnalyzer().analyze(p)
    assert any(i["code"] == "daily-hours-range" for i in result["rule_issues"])


def test_weekday_hours_round_trip_through_api_and_optimization_is_not_saved(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from escala_analyzer.container import ApplicationContainer
    from escala_analyzer.infrastructure.json_repository import JsonProjectRepository
    from escala_analyzer.presentation import local as main

    repository = JsonProjectRepository(tmp_path / "project.json")
    p = make_project()
    p.groups[0].allow_hours_optimization = True
    p.groups[0].work_hours_by_weekday = [None, None, None, None, 6, None, None]
    monkeypatch.setattr(main, "container", ApplicationContainer(repository=repository))
    with TestClient(main.app) as client:
        saved = client.put("/api/project", json=EntityCodec.dump(p, mode="json"))
        assert saved.status_code == 200
        before = repository.path.read_bytes()
        assert client.get("/api/project").json()["groups"][0]["work_hours_by_weekday"][4] == 6
        result = client.post(
            "/api/optimize",
            json={
                "project": saved.json(),
                "options": {
                    "optimize_work_hours": True,
                    "max_groups": 1,
                    "max_employees": 3,
                    "max_solutions": 3,
                    "time_limit_seconds": 8,
                },
            },
        )
        assert result.status_code == 200
        assert any(s["hour_changes"] for s in result.json()["solutions"])
        assert repository.path.read_bytes() == before
        assert (
            client.post(
                "/api/optimize",
                json={"project": saved.json(), "options": {"hours_step_minutes": 0}},
            ).status_code
            == 422
        )


def test_hours_solver_uses_future_rules_within_the_annual_profile():
    from escala_analyzer.domain.entities import RulePeriod

    p = make_project()
    p.groups[0].allow_hours_optimization = True
    p.rule_periods = [
        RulePeriod(
            effective_from=date(2026, 7, 1),
            label="Nova carga",
            rules=replace(p.rules, weekly_max_hours=36),
        )
    ]
    optimized, report = GroupHoursOptimizer().optimize(p, 15, 5)
    assert report["status"] == "optimized"
    result = ProjectAnalyzer().analyze(optimized)
    assert not any(i["code"] == "rolling-hours" for i in result["rule_issues"])
    actual = result["group_annual"][0]["allocations"][0]["journeys"]
    assert all(j["work_hours"] == 6 for j in actual)


def test_hours_solver_accounts_for_break_minimum_using_net_hours():
    p = make_project()
    p.groups[0].allow_hours_optimization = True
    p.shifts[0].break_minutes = 45
    optimized, report = GroupHoursOptimizer().optimize(p, 15, 5)
    assert report["status"] == "optimized"
    result = ProjectAnalyzer().analyze(optimized)
    assert not any(i["code"] == "intrajornada" for i in result["rule_issues"])
    actual = result["group_annual"][0]["allocations"][0]["journeys"]
    assert all(j["work_hours"] == 6 for j in actual)
    assert actual[0]["end"].endswith("14:45:00")
