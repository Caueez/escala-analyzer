import pytest
from test_schedule_optimizer import project

from escala_analyzer.domain.entities import BusinessConstraints, ProjectState, ScheduleGroup
from escala_analyzer.domain.policies.business_constraints import (
    allowed_cycle,
    business_metrics,
    pattern_key,
)
from escala_analyzer.infrastructure.optimization.schedule_optimizer import (
    OptimizationCycle,
    OptimizationOptions,
    ScheduleOptimizer,
)


def opts(**kwargs):
    return OptimizationOptions(
        automatic_cycles=False,
        cycles=[OptimizationCycle(cycle_blocks=[1, 1])],
        max_solutions=3,
        time_limit_seconds=3,
        **kwargs,
    )


def test_patterns_ignore_phase_rotations_and_repeated_periods():
    assert pattern_key([1, 1, 1, 1]) == pattern_key([1, 1])
    assert pattern_key([5, 2, 3, 1]) == pattern_key([3, 1, 5, 2])
    assert pattern_key([5, 2, 3]) == pattern_key([8, 2])
    p = project()
    p.groups = [
        ScheduleGroup(
            id=str(i), name="G", shift_id="day", work_days=1, rest_days=1, cycle_phase_offset=i
        )
        for i in range(4)
    ]
    metrics, issues = business_metrics(p, 4)
    assert metrics["pattern_count"] == 1
    assert not issues


def test_default_policy_rejects_light_work_and_long_rest():
    policy = BusinessConstraints()
    assert not allowed_cycle([1, 4], policy)
    assert not allowed_cycle([4, 4], policy)
    assert allowed_cycle([5, 2], policy)
    assert allowed_cycle([5, 2, 3, 1, 2], policy)
    assert allowed_cycle(
        [1, 4], BusinessConstraints(min_work_percent=0, max_consecutive_rest_days=None)
    )


def test_manual_candidates_cannot_bypass_business_limits():
    options = opts()
    options.cycles = [OptimizationCycle(cycle_blocks=[1, 4])]
    result = ScheduleOptimizer().optimize(project(), options)
    assert len(result["solutions"]) == 1
    assert result["solutions"][0]["baseline"]
    assert result["metrics"]["deficit_staff_days"] > 0
    assert result["warnings"]


@pytest.mark.parametrize("existing", [False, True])
def test_budget_is_hard_even_when_coverage_has_higher_priority(existing):
    p = project(2)
    p.business_constraints = BusinessConstraints(
        monthly_employee_cost=4000, monthly_budget=8000, max_schedule_patterns=1
    )
    if existing:
        p.groups = [
            ScheduleGroup(id="a", name="A", shift_id="day", work_days=1, rest_days=1),
            ScheduleGroup(
                id="b", name="B", shift_id="day", work_days=1, rest_days=1, cycle_phase_offset=1
            ),
        ]
    result = ScheduleOptimizer().optimize(p, opts(optimize_existing=existing))
    assert any(not s["baseline"] for s in result["solutions"])
    for s in result["solutions"]:
        if not s["baseline"]:
            assert s["metrics"]["people_total"] <= 2
            assert s["metrics"]["monthly_staff_cost"] <= 8000
            assert s["metrics"]["pattern_count"] <= 1
            assert s["business_acceptable"]
    assert result["metrics"]["deficit_staff_days"] > 0


def test_existing_baseline_over_budget_is_visible_but_not_acceptable():
    p = project()
    p.groups = [ScheduleGroup(id="a", name="A", shift_id="day", employee_count=9)]
    p.business_constraints = BusinessConstraints(monthly_employee_cost=4000, monthly_budget=8000)
    result = ScheduleOptimizer().optimize(p, opts(max_groups=1))
    baseline = next(s for s in result["solutions"] if s["baseline"])
    assert baseline["metrics"]["monthly_staff_cost"] == 36000
    assert not baseline["business_acceptable"]
    assert any(issue["code"] == "monthly-budget" for issue in baseline["issues"])
    assert baseline["project"]["groups"][0]["employee_count"] == 9


def test_policy_validation_and_legacy_priority_migration():
    with pytest.raises(ValueError):
        BusinessConstraints(monthly_budget=100, monthly_employee_cost=0)
    with pytest.raises(ValueError):
        BusinessConstraints(max_schedule_patterns=0)
    legacy = [
        "deficit_staff_days",
        "deficit_work_hours",
        "rule_violation_count",
        "group_count",
        "surplus_staff_days",
        "people_total",
    ]
    p = ProjectState(optimization_priorities=legacy)
    assert p.optimization_priorities[:6] == legacy
    assert set(p.optimization_priorities[6:]) == {"pattern_count", "monthly_staff_cost"}


def test_budget_priority_guides_solver_and_ranking():
    p = project()
    p.business_constraints = BusinessConstraints(monthly_employee_cost=4000)
    p.optimization_priorities.remove("monthly_staff_cost")
    p.optimization_priorities.insert(0, "monthly_staff_cost")
    result = ScheduleOptimizer().optimize(p, opts())
    assert result["stages"][0]["objective"] == "monthly_staff_cost"
    assert result["metrics"]["monthly_staff_cost"] == 0
    assert all(s["ranking"][0] == s["metrics"]["monthly_staff_cost"] for s in result["solutions"])


def test_pattern_limit_is_shared_by_existing_groups_and_new_phases():
    p = project(1)
    p.groups = [ScheduleGroup(id="a", name="A", shift_id="day", work_days=1, rest_days=1)]
    p.business_constraints = BusinessConstraints(max_schedule_patterns=1)
    options = opts()
    options.cycles = [
        OptimizationCycle(cycle_blocks=[1, 1]),
        OptimizationCycle(cycle_blocks=[2, 1]),
    ]
    result = ScheduleOptimizer().optimize(p, options)
    assert result["metrics"]["deficit_staff_days"] == 0
    for solution in result["solutions"]:
        assert solution["metrics"]["pattern_count"] <= 1
        assert all(
            pattern_key(g["cycle_blocks"] or [g["work_days"], g["rest_days"]]) == (1, 1)
            for g in solution["project"]["groups"]
        )


def test_existing_mode_consolidates_distinct_patterns_with_global_limit():
    p = project(1)
    p.groups = [
        ScheduleGroup(id="a", name="A", shift_id="day", work_days=1, rest_days=1),
        ScheduleGroup(id="b", name="B", shift_id="day", work_days=2, rest_days=1),
    ]
    p.business_constraints = BusinessConstraints(max_schedule_patterns=1)
    result = ScheduleOptimizer().optimize(p, opts(optimize_existing=True))
    assert result["solutions"][0]["business_acceptable"]
    assert result["metrics"]["pattern_count"] == 1
    baseline = next(s for s in result["solutions"] if s["baseline"])
    assert not baseline["business_acceptable"]
