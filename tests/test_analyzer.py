from datetime import date

from escala_analyzer.domain.analysis.project_analyzer import analyze_project, is_working
from escala_analyzer.domain.entities import (
    ProjectState,
    RuleSettings,
    ScheduleGroup,
    Shift,
)


def small_project(group: ScheduleGroup) -> ProjectState:
    return ProjectState(
        name="Teste",
        year=2027,
        selected_month=1,
        shifts=[
            Shift(
                id="morning",
                name="Manhã",
                hours_per_day=8,
                demand_by_weekday=[1] * 7,
            )
        ],
        groups=[group],
        rules=RuleSettings(
            profile="baseline",
            weekly_max_hours=44,
            min_rest_days_in_rolling_7=1,
            min_sundays_off_per_month=0,
            min_days_off_per_month=0,
            check_min_days_off_per_month=False,
            max_consecutive_work_days=6,
        ),
    )


def test_cycle_repeats_from_anchor_date() -> None:
    group = ScheduleGroup(
        id="g1",
        name="Grupo A",
        shift_id="morning",
        employee_count=4,
        work_days=3,
        rest_days=1,
        cycle_anchor=date(2027, 1, 1),
    )
    assert is_working(group, date(2027, 1, 1)) is True
    assert is_working(group, date(2027, 1, 2)) is True
    assert is_working(group, date(2027, 1, 3)) is True
    assert is_working(group, date(2027, 1, 4)) is False
    assert is_working(group, date(2027, 1, 5)) is True


def test_manual_override_takes_precedence_over_cycle() -> None:
    group = ScheduleGroup(
        id="g1",
        name="Grupo A",
        shift_id="morning",
        employee_count=4,
        work_days=3,
        rest_days=1,
        cycle_anchor=date(2027, 1, 1),
        overrides={"2027-01-01": False, "2027-01-04": True},
    )
    assert is_working(group, date(2027, 1, 1)) is False
    assert is_working(group, date(2027, 1, 4)) is True


def test_analyzer_reports_coverage_gap_on_group_rest_day() -> None:
    group = ScheduleGroup(
        id="g1",
        name="Grupo A",
        shift_id="morning",
        employee_count=1,
        work_days=1,
        rest_days=1,
        cycle_anchor=date(2027, 1, 1),
    )
    result = analyze_project(small_project(group))
    day_2 = next(item for item in result["coverage_by_day"] if item["date"] == "2027-01-02")
    assert day_2["shifts"][0]["scheduled"] == 0
    assert day_2["shifts"][0]["deficit"] == 1
    assert result["coverage_gap_count"] > 0


def test_analyzer_counts_group_monthly_sunday_rest() -> None:
    group = ScheduleGroup(
        id="g1",
        name="Grupo A",
        shift_id="morning",
        employee_count=1,
        work_days=1,
        rest_days=1,
        cycle_anchor=date(2027, 1, 1),
    )
    project = small_project(group)
    project.rules.min_sundays_off_per_month = 1
    result = analyze_project(project)
    january = next(
        item for item in result["group_monthly"] if item["group_id"] == "g1" and item["month"] == 1
    )
    assert january["sundays_off"] >= 2
    assert not any(
        issue["code"] == "monthly-sunday-rest" and issue["month"] == 1
        for issue in result["rule_issues"]
    )
