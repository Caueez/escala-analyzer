from datetime import date

from escala_analyzer.domain.analysis.schedule_rules_analyzer import ScheduleRulesAnalyzer
from escala_analyzer.domain.entities import ProjectState, RuleSettings, ScheduleGroup, Shift
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec


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

    assert any(issue["code"] == "monthly-rest-days" for issue in result["rule_issues"])


def test_minimum_sundays_off_rule() -> None:
    project = make_project(min_sundays_off_per_month=5)

    result = analyze(project)

    assert any(issue["code"] == "monthly-sunday-rest" for issue in result["rule_issues"])


def test_rolling_rest_rule() -> None:
    project = make_project(
        work_days=6,
        rest_days=1,
        min_rest_days_in_rolling_7=2,
    )

    result = analyze(project)

    assert any(issue["code"] == "rolling-rest" for issue in result["rule_issues"])


def test_rolling_hours_rule() -> None:
    project = make_project(
        work_days=6,
        rest_days=1,
        weekly_max_hours=40,
    )

    result = analyze(project)

    assert any(issue["code"] == "rolling-hours" for issue in result["rule_issues"])


def test_consecutive_work_rule() -> None:
    project = make_project(
        work_days=6,
        rest_days=1,
        max_consecutive_work_days=5,
    )

    result = analyze(project)

    assert any(issue["code"] == "consecutive-work" for issue in result["rule_issues"])


def test_monthly_and_annual_hours_and_weekday_rest_are_consistent():
    from datetime import time

    project = make_project()
    project.shifts[0].start_time = time(22)
    project.shifts[0].break_minutes = 60
    result = analyze(project)
    annual = result["group_annual"][0]
    assert sum(annual["days_off_by_weekday"]) == annual["days_off"]
    assert annual["work_hours"] == sum(row["work_hours"] for row in result["group_monthly"])
    assert annual["days_off_by_weekday"] == [
        sum(row["days_off_by_weekday"][i] for row in result["group_monthly"]) for i in range(7)
    ]
    assert annual["rest_hours"] + annual["work_hours"] + annual["break_hours"] == 365 * 24
    journey = result["group_monthly"][0]["allocations"][0]["journeys"][0]
    assert journey["start"] == "2026-01-01T22:00:00"
    assert journey["end"] == "2026-01-02T07:00:00"
    assert result["group_monthly"][0]["min_intershift_hours"] == 15


def test_rotation_uses_actual_shift_hours_for_rolling_rule():
    from datetime import time

    project = make_project(work_days=1, rest_days=1, weekly_max_hours=40)
    project.shifts[0].hours_per_day = 12
    project.shifts[0].start_time = time(22)
    project.shifts.append(Shift(id="short", name="Curto", hours_per_day=2, start_time=time(6)))
    group = project.groups[0]
    group.rotation_shift_ids = ["shift-1", "short"]
    group.allocations = {"shift-1": 5, "short": 5}
    result = analyze(project)
    assert not any(issue["code"] == "rolling-hours" for issue in result["rule_issues"])
    journeys = result["group_monthly"][0]["allocations"][0]["journeys"]
    assert [journey["work_hours"] for journey in journeys[:4]] == [12, 2, 12, 2]


def test_intershift_includes_interval_overnight_and_previous_year():
    from datetime import time

    project = make_project(work_days=1, rest_days=1)
    project.shifts[0].hours_per_day = 24
    project.shifts[0].start_time = time(23)
    project.shifts.append(Shift(id="short", name="Curto", hours_per_day=2, start_time=time(0)))
    group = project.groups[0]
    group.rotation_shift_ids = ["shift-1", "short"]
    group.allocations = {"shift-1": 5, "short": 5}
    project.rules.check_intershift_rest = True
    project.rules.min_intershift_hours = 11
    result = analyze(project)
    assert any(issue["code"] == "interjornada" for issue in result["rule_issues"])
    assert (
        result["group_monthly"][0]["allocations"][0]["journeys"][0]["rest_before_hours"] is not None
    )


def test_fixed_allocations_have_individual_hours_and_break_checks():
    from datetime import time

    project = make_project()
    project.shifts[0].start_time = time(8)
    project.shifts[0].break_minutes = 60
    project.shifts.append(Shift(id="short", name="Curto", hours_per_day=5, start_time=time(8)))
    project.groups[0].allocations["short"] = 3
    project.rules.check_breaks = True
    result = analyze(project)
    allocations = result["group_monthly"][0]["allocations"]
    assert len(allocations) == 2
    assert allocations[0]["work_hours"] / 8 == allocations[1]["work_hours"] / 5
    assert any(
        issue["code"] == "intrajornada" and issue["shift_name"] == "Curto"
        for issue in result["rule_issues"]
    )


def test_rolling_windows_include_year_end_boundary():
    from datetime import timedelta

    project = make_project(work_days=1, rest_days=31, weekly_max_hours=48)
    group = project.groups[0]
    # Only the window starting on Dec 31 reaches seven working dates.
    day = date(2026, 12, 25)
    while day <= date(2027, 1, 6):
        group.overrides[day.isoformat()] = day >= date(2026, 12, 31)
        day += timedelta(days=1)
    result = analyze(project)
    assert any(
        issue["code"] == "rolling-hours"
        and issue["month"] == 12
        and issue["last_window_start"] == "2026-12-31"
        for issue in result["rule_issues"]
    )


def test_break_accounting_is_independent_of_minimum_validation():
    from datetime import time

    project = make_project(weekly_max_hours=37)
    shift = project.shifts[0]
    shift.hours_per_day = 8
    shift.hours_include_break = True
    shift.break_minutes = 45
    shift.start_time = time(8)
    project.rules.check_breaks = False
    result = analyze(project)
    journey = result["group_annual"][0]["allocations"][0]["journeys"][0]
    assert journey["work_hours"] == 7.25
    assert journey["break_minutes"] == 45
    assert journey["start"].endswith("08:00:00")
    assert journey["end"].endswith("16:00:00")
    assert not any(i["code"] in {"intrajornada", "rolling-hours"} for i in result["rule_issues"])
    annual = result["group_annual"][0]
    assert annual["work_hours"] == annual["work_days"] * 7.25
    assert annual["break_hours"] == annual["work_days"] * 0.75
    assert annual["min_intershift_hours"] == 16
    project.rules.check_breaks = True
    validated = analyze(project)
    issue = next(i for i in validated["rule_issues"] if i["code"] == "intrajornada")
    assert issue["actual"] == 45
    assert issue["expected"] == 60
    assert issue["configuration_section"] == "timingRules"
    assert validated["group_annual"][0]["work_hours"] == annual["work_hours"]
    project.rules.min_break_over_6h_minutes = 45
    assert not any(i["code"] == "intrajornada" for i in analyze(project)["rule_issues"])


def test_legacy_effective_hours_do_not_change_when_loading_old_shift():
    shift = EntityCodec.load(
        Shift, {"id": "old", "name": "Antigo", "hours_per_day": 8, "break_minutes": 45}
    )
    assert shift.hours_include_break is False
    assert shift.work_hours == 8
    assert shift.elapsed_hours == 8.75
    assert EntityCodec.load(Shift, EntityCodec.dump(shift)).work_hours == 8


def test_gross_duration_cannot_be_less_than_break():
    import pytest

    with pytest.raises(ValueError):
        Shift(
            id="s", name="Inválido", hours_per_day=0.5, break_minutes=45, hours_include_break=True
        )


def test_minimum_break_threshold_uses_effective_hours():
    project = make_project()
    project.shifts[0].hours_per_day = 6.5
    project.shifts[0].hours_include_break = True
    project.shifts[0].break_minutes = 45
    project.rules.check_breaks = True
    assert not any(i["code"] == "intrajornada" for i in analyze(project)["rule_issues"])
