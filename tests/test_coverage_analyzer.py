
from datetime import date

from escala_analyzer.domain.coverage_analyzer import CoverageAnalyzer
from escala_analyzer.domain.models import ProjectState, ScheduleGroup, Shift


def make_project() -> ProjectState:
    return ProjectState(
        name="Teste",
        year=2026,
        selected_month=1,
        shifts=[
            Shift(
                id="shift-1",
                name="Manhã",
                hours_per_day=8,
                demand_by_weekday=[3, 3, 3, 3, 3, 2, 1],
            )
        ],
        groups=[
            ScheduleGroup(
                id="group-1",
                name="Grupo A",
                shift_id="shift-1",
                employee_count=2,
                work_days=5,
                rest_days=2,
                cycle_anchor=date(2026, 1, 1),
            )
        ],
    )


def test_coverage_analyzer_detects_staff_deficit() -> None:
    project = make_project()

    result = CoverageAnalyzer().analyze(
        project=project,
        calendar_dates=[date(2026, 1, 1)],
    )

    day = result["coverage_by_day"][0]
    shift = day["shifts"][0]

    assert shift["required"] == 3
    assert shift["scheduled"] == 2
    assert shift["deficit"] == 1
    assert shift["surplus"] == 0
    assert len(result["coverage_issues"]) == 1


def test_coverage_analyzer_detects_surplus() -> None:
    project = make_project()
    project.shifts[0].demand_by_weekday = [1, 1, 1, 1, 1, 1, 1]

    result = CoverageAnalyzer().analyze(
        project=project,
        calendar_dates=[date(2026, 1, 1)],
    )

    shift = result["coverage_by_day"][0]["shifts"][0]

    assert shift["required"] == 1
    assert shift["scheduled"] == 2
    assert shift["deficit"] == 0
    assert shift["surplus"] == 1
    assert result["coverage_issues"] == []


def test_coverage_analyzer_accumulates_monthly_totals() -> None:
    project = make_project()

    result = CoverageAnalyzer().analyze(
        project=project,
        calendar_dates=[
            date(2026, 1, 1),
            date(2026, 1, 2),
        ],
    )

    assert result["monthly_required"][(1, "shift-1")] == 6
    assert result["monthly_scheduled"][(1, "shift-1")] == 4
    assert result["monthly_coverage_counts"][1] == 2
    assert result["monthly_peak_deficit"][1] == 1
