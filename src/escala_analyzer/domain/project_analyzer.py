
"""Fachada pública para análise de escalas."""

from __future__ import annotations

from datetime import date
from typing import Any

from .coverage_analyzer import CoverageAnalyzer
from .models import ProjectState
from .schedule_calendar import ScheduleCalendar
from .schedule_rules_analyzer import ScheduleRulesAnalyzer


class ProjectAnalyzer:
    """Orquestra as análises de cobertura e regras de jornada."""

    def __init__(
        self,
        coverage_analyzer: CoverageAnalyzer | None = None,
        rules_analyzer: ScheduleRulesAnalyzer | None = None,
    ) -> None:
        self._coverage_analyzer = coverage_analyzer or CoverageAnalyzer()
        self._rules_analyzer = rules_analyzer or ScheduleRulesAnalyzer()

    def analyze(self, project: ProjectState) -> dict[str, Any]:
        year_start = date(project.year, 1, 1)
        year_end = date(project.year, 12, 31)
        calendar_dates = ScheduleCalendar.year_dates(project.year)

        shifts = {shift.id: shift for shift in project.shifts}

        coverage_result = self._coverage_analyzer.analyze(
            project=project,
            calendar_dates=calendar_dates,
        )

        rules_result = self._rules_analyzer.analyze(
            project=project,
            year_start=year_start,
            year_end=year_end,
            shifts=shifts,
        )

        coverage_by_day = coverage_result["coverage_by_day"]
        coverage_issues = coverage_result["coverage_issues"]
        group_monthly = rules_result["group_monthly"]
        rule_issues = rules_result["rule_issues"]

        monthly_coverage_counts = coverage_result["monthly_coverage_counts"]
        monthly_peak_deficit = coverage_result["monthly_peak_deficit"]
        monthly_max_shortage_by_shift = (
            coverage_result["monthly_max_shortage_by_shift"]
        )
        monthly_required = coverage_result["monthly_required"]
        monthly_scheduled = coverage_result["monthly_scheduled"]

        monthly_summary: list[dict[str, Any]] = []

        for month in range(1, 13):
            shift_rows = []

            for shift in project.shifts:
                shift_rows.append(
                    {
                        "shift_id": shift.id,
                        "shift_name": shift.name,
                        "required_staff_days": monthly_required[(month, shift.id)],
                        "scheduled_staff_days": monthly_scheduled[(month, shift.id)],
                        "max_daily_deficit": monthly_max_shortage_by_shift[
                            (month, shift.id)
                        ],
                    }
                )

            monthly_summary.append(
                {
                    "month": month,
                    "month_name": ScheduleRulesAnalyzer.MONTH_NAMES[month - 1],
                    "coverage_gap_count": monthly_coverage_counts[month],
                    "worst_single_shift_deficit": monthly_peak_deficit[month],
                    "shifts": shift_rows,
                }
            )

        issues = coverage_issues + rule_issues
        months_with_issues = sorted(
            {
                issue["month"]
                for issue in issues
                if issue.get("month")
            }
        )

        return {
            "year": project.year,
            "days_in_year": len(calendar_dates),
            "people_total": sum(
                group.employee_count for group in project.groups
            ),
            "group_count": len(project.groups),
            "shift_count": len(project.shifts),
            "coverage_gap_count": len(coverage_issues),
            "days_with_any_coverage_gap": len(
                {item["date"] for item in coverage_issues}
            ),
            "peak_single_shift_deficit": max(
                (item["deficit"] for item in coverage_issues),
                default=0,
            ),
            "rule_issue_count": len(rule_issues),
            "months_with_issues": months_with_issues,
            "rules": project.rules.model_dump(mode="json"),
            "coverage_by_day": coverage_by_day,
            "coverage_issues": coverage_issues,
            "group_monthly": group_monthly,
            "monthly_summary": monthly_summary,
            "rule_issues": rule_issues,
            "issues": issues,
            "is_legal_opinion": False,
            "disclaimer": (
                "A análise verifica somente os parâmetros configurados no projeto. "
                "Ela não substitui legislação consolidada, convenção/acordo coletivo, "
                "regras específicas da categoria nem validação profissional."
            ),
        }


def analyze_project(project: ProjectState) -> dict[str, Any]:
    """Mantém a função pública usada pela API e pelos demais módulos."""
    return ProjectAnalyzer().analyze(project)


def is_working(group: Any, day: date) -> bool:
    """Mantém compatibilidade com imports anteriores."""
    from .schedule_calendar import ScheduleCalendar

    return ScheduleCalendar.is_working(group, day)
