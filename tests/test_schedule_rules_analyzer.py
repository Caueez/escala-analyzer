
from datetime import date

from escala_analyzer.domain.models import ProjectState, RuleSettings, ScheduleGroup, Shift
from escala_analyzer.domain.schedule_rules_analyzer import ScheduleRulesAnalyzer


def make_project(
    *,
    work_days: int = 5,
    rest_days: int = 2,
    min_days_off_per_month: int = 0,
    min_sundays_off_per_month: int = 0,
    min_rest_days_in_rolling_7: int = 0,
    weekly_max_hours: float = 168.0,
    max_consecutive_work_days: int = 7,
    check_min_days_off_per_month: bool = False,
) -> ProjectState:
    return ProjectState(
        name="Teste",
        year=2026,
        selected_month=1,
        shifts=[
            Shift(
                id="shift-1",
                name="Manhã",
                hours_per_day=8,
                demand_by_weekday=[1, 1, 1, 1, 1, 1, 1],
            )
        ],
        groups=[
            ScheduleGroup(
                id="group-1",
                name="Grupo A",
                shift_id="shift-1",
                employee_count=5,
                work_days=work_days,
                rest_days=rest_days,
                cycle_anchor=date(2026, 1, 1),
            )
        ],
        rules=RuleSettings(
            profile="baseline",
            weekly_max_hours=weekly_max_hours,
            min_rest_days_in_rolling_7=min_rest_days_in_rolling_7,
            min_sundays_off_per_month=min_sundays_off_per_month,
            min_days_off_per_month=min_days_off_per_month,
            check_min_days_off_per_month=check_min_days_off_per_month,
            max_consecutive_work_days=max_consecutive_work_days,
        ),
    )


def analyze(project: ProjectState) -> dict:
    return ScheduleRulesAnalyzer().analyze(
        project=project,
        year_start=date(project.year, 1, 1),
        year_end=date(project.year, 12, 31),
        shifts={shift.id: shift for shift in project.shifts},
    )


def test_monthly_summary_contains_all_twelve_months() -> None:
    result = analyze(make_project())

    assert len(result["group_monthly"]) == 12
    assert result["group_monthly"][0]["month"] == 1
    assert result["group_monthly"][-1]["month"] == 12


def test_minimum_monthly_rest_rule_can_be_enabled() -> None:
    project = make_project(
        work_days=6,
        rest_days=1,
        min_days_off_per_month=8,
        check_min_days_off_per_month=True,
    )

    result = analyze(project)

    assert any(
        issue["code"] == "monthly-rest-days"
        for issue in result["rule_issues"]
    )


def test_minimum_sundays_off_rule() -> None:
    project = make_project(min_sundays_off_per_month=5)

    result = analyze(project)

    assert any(
        issue["code"] == "monthly-sunday-rest"
        for issue in result["rule_issues"]
    )


def test_rolling_rest_rule() -> None:
    project = make_project(
        work_days=6,
        rest_days=1,
        min_rest_days_in_rolling_7=2,
    )

    result = analyze(project)

    assert any(
        issue["code"] == "rolling-rest"
        for issue in result["rule_issues"]
    )



def test_rolling_hours_rule() -> None:
    project = make_project(
        work_days=6,
        rest_days=1,
        weekly_max_hours=40,
    )

    result = analyze(project)

    assert any(
        issue["code"] == "rolling-hours"
        for issue in result["rule_issues"]
    )


def test_consecutive_work_rule() -> None:
    project = make_project(
        work_days=6,
        rest_days=1,
        max_consecutive_work_days=5,
    )

    result = analyze(project)

    assert any(
        issue["code"] == "consecutive-work"
        for issue in result["rule_issues"]
    )
