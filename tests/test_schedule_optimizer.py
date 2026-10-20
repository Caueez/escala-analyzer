from dataclasses import replace
from datetime import date, time

from escala_analyzer.domain.entities import ProjectState, RuleSettings, ScheduleGroup, Shift
from escala_analyzer.infrastructure.optimization.schedule_optimizer import (
    OptimizationCycle,
    OptimizationOptions,
    ScheduleOptimizer,
)
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec


def project(demand=1):
    return ProjectState(
        name="Busca",
        year=2026,
        shifts=[
            Shift(
                id="day",
                name="Dia",
                hours_per_day=8,
                start_time=time(8),
                break_minutes=60,
                demand_by_weekday=[demand] * 7,
            )
        ],
        rules=RuleSettings(
            weekly_max_hours=168,
            min_rest_days_in_rolling_7=0,
            min_sundays_off_per_month=0,
            check_min_days_off_per_month=False,
            max_consecutive_work_days=31,
            check_breaks=True,
            check_intershift_rest=True,
        ),
    )


def options(**kwargs):
    return OptimizationOptions(
        cycles=[OptimizationCycle(work_days=1, rest_days=1)], time_limit_seconds=3, **kwargs
    )


def test_baseline_always_present_and_all_existing_groups_unchanged():
    original = project(2)
    original.groups = [
        ScheduleGroup(
            id="keep",
            name="Não alterar",
            shift_id="day",
            employee_count=1,
            cycle_anchor=date(2025, 3, 2),
            cycle_phase_offset=7,
            overrides={"2026-01-01": False},
        )
    ]
    before = EntityCodec.dump(original, mode="json")
    result = ScheduleOptimizer().optimize(original, options(max_solutions=3))
    assert len(result["solutions"]) >= 2
    assert EntityCodec.dump(original, mode="json") == before
    for solution in result["solutions"]:
        assert solution["project"]["groups"][0] == before["groups"][0]
        assert solution["optimal"] is False
    baseline = next(s for s in result["solutions"] if s["baseline"])
    assert baseline["project"] == before
    assert result["solutions"] == sorted(result["solutions"], key=lambda s: s["ranking"])


def test_invalid_groups_are_kept_and_their_issues_reported():
    original = project()
    original.shifts[0].break_minutes = 0
    original.groups = [ScheduleGroup(id="bad", name="Inválido", shift_id="day")]
    result = ScheduleOptimizer().optimize(original, options(max_solutions=2))
    baseline = next(s for s in result["solutions"] if s["baseline"])
    assert any(issue["code"] == "intrajornada" for issue in baseline["issues"])
    assert baseline["metrics"]["rule_violation_count"] > 0
    assert baseline["project"]["groups"][0]["id"] == "bad"
    assert result["rejected_patterns"] == []


def test_no_addition_slots_still_returns_baseline_with_deficit():
    result = ScheduleOptimizer().optimize(project(3), options(max_groups=0))
    assert result["status"] == "partial"
    assert len(result["solutions"]) == 1
    assert result["solutions"][0]["metrics"]["deficit_staff_days"] == 365 * 3
    assert result["search_complete"]


def test_existing_limits_exceeded_reported_without_dropping_groups():
    original = project()
    original.groups = [ScheduleGroup(id="keep", name="Grande", shift_id="day", employee_count=8)]
    result = ScheduleOptimizer().optimize(
        original, options(max_groups=0, max_employees=0, max_group_size=2)
    )
    baseline = result["solutions"][0]
    assert baseline["project"]["groups"][0]["allocations"] == {"day": 8}
    assert baseline["metrics"]["limit_violation_count"] == 3
    assert {"group-limit", "people-limit", "group-size-limit"} <= {
        i["code"] for i in baseline["issues"]
    }


def test_limit_one_stops_with_baseline_and_explains_truncation():
    result = ScheduleOptimizer().optimize(project(), options(max_solutions=1))
    assert result["solutions_found"] == 1
    assert result["solutions"][0]["baseline"]
    assert result["truncated"]
    assert not result["search_complete"]
    assert not result["stages"]


def test_timeout_retains_baseline(monkeypatch):
    from escala_analyzer.infrastructure.optimization import schedule_optimizer

    calls = 0

    def expired():
        nonlocal calls
        calls += 1
        return 0.0 if calls == 1 else 100.0

    monkeypatch.setattr(schedule_optimizer, "monotonic", expired)
    result = ScheduleOptimizer().optimize(project(), options())
    assert result["status"] == "timeout"
    assert result["project"] is not None
    assert result["solutions_found"] == 1
    assert result["solutions"][0]["baseline"]


def test_ranking_has_satisfaction_order_and_deficit_covering_alternative():
    result = ScheduleOptimizer().optimize(project(), options(max_solutions=3))
    assert any(s["metrics"]["deficit_staff_days"] == 0 for s in result["solutions"])
    for solution in result["solutions"]:
        metrics = solution["metrics"]
        assert solution["ranking"] == [
            metrics[k]
            for k in (
                "deficit_staff_days",
                "deficit_work_hours",
                "rule_violation_count",
                "pattern_count",
                "monthly_staff_cost",
                "group_count",
                "surplus_staff_days",
                "people_total",
            )
        ]
    assert result["solutions_found"] == len(result["solutions"]) <= 3
    assert len({str(s["project"]["groups"]) for s in result["solutions"]}) == len(
        result["solutions"]
    )


def test_rotation_overrides_and_multi_shift_allocations_preserved():
    original = project()
    original.shifts.append(replace(original.shifts[0], id="night"))
    original.groups = [
        ScheduleGroup(
            id="rotate",
            name="Rotativo",
            employee_count=2,
            allocations={"day": 2, "night": 2},
            rotation_shift_ids=["day", "night"],
            overrides={"2026-01-03": True},
            work_days=2,
            rest_days=2,
        )
    ]
    before = EntityCodec.dump(original.groups[0], mode="json")
    result = ScheduleOptimizer().optimize(original, options(max_solutions=2))
    for solution in result["solutions"]:
        assert solution["project"]["groups"][0] == before


def test_daily_minimum_has_priority_over_rule_compliance():
    original = project(2)
    original.shifts[0].break_minutes = 0  # Every new team violates enabled break checks.
    original.shifts[0].demand_by_date["2026-01-01"] = 3
    result = ScheduleOptimizer().optimize(original, options(max_solutions=3))
    best = result["solutions"][0]
    baseline = next(solution for solution in result["solutions"] if solution["baseline"])
    assert best["metrics"]["deficit_staff_days"] == 0
    assert best["metrics"]["rule_violation_count"] > baseline["metrics"]["rule_violation_count"]
    assert baseline["metrics"]["rule_violation_count"] == 0
    assert baseline["metrics"]["deficit_staff_days"] > 0
    assert result["stages"][0]["objective"] == "deficit_staff_days"
    from escala_analyzer.domain.analysis.project_analyzer import ProjectAnalyzer

    analysis = ProjectAnalyzer().analyze(
        EntityCodec.load(ProjectState, best["project"]), include_details=False
    )
    assert all(
        shift["scheduled"] >= shift["required"]
        for day in analysis["coverage_by_day"]
        for shift in day["shifts"]
    )


def test_disabled_mixing_only_adds_existing_cycle_type():
    original = project(2)
    original.groups = [
        ScheduleGroup(
            id="fixed", name="Fixo", shift_id="day", work_days=1, rest_days=1, employee_count=1
        )
    ]
    result = ScheduleOptimizer().optimize(
        original,
        OptimizationOptions(
            automatic_cycles=False,
            cycles=[
                OptimizationCycle(work_days=1, rest_days=1),
                OptimizationCycle(work_days=2, rest_days=1),
            ],
            allow_mixed_cycles_per_shift=False,
            time_limit_seconds=3,
            max_solutions=2,
        ),
    )
    assert len(result["solutions"]) == 2
    for solution in result["solutions"]:
        assert all(
            g["cycle_blocks"] in (None, [1, 1]) and g["work_days"] == 1
            for g in solution["project"]["groups"]
        )


def test_enabled_mixing_combines_two_cycle_types_in_one_shift():
    original = project(2)
    original.groups = [
        ScheduleGroup(
            id="fixed", name="Fixo", shift_id="day", work_days=1, rest_days=1, employee_count=1
        )
    ]
    result = ScheduleOptimizer().optimize(
        original,
        OptimizationOptions(
            automatic_cycles=False,
            cycles=[OptimizationCycle(work_days=2, rest_days=1)],
            allow_mixed_cycles_per_shift=True,
            time_limit_seconds=3,
            max_solutions=2,
        ),
    )
    proposal = next(s for s in result["solutions"] if not s["baseline"])
    assert {(g["work_days"], g["rest_days"]) for g in proposal["project"]["groups"]} == {
        (1, 1),
        (2, 1),
    }
