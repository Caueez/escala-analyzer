"""Cálculo de cobertura diária e consolidação mensal."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.contracts.analysis_contracts import (
    AnalysisIssue,
    CoverageResult,
    DayCoverage,
    DayCoverageResult,
    ShiftCoverage,
)
from escala_analyzer.domain.entities import ProjectState, ScheduleGroup


class CoverageAnalyzer:
    """Calcula a cobertura necessária e prevista para cada turno."""

    def analyze(
        self,
        project: ProjectState,
        calendar_dates: list[date],
    ) -> CoverageResult:
        groups_by_shift = self._group_by_shift(project.groups)

        coverage_by_day: list[DayCoverage] = []
        coverage_issues: list[AnalysisIssue] = []

        monthly_coverage_counts: dict[int, int] = defaultdict(int)
        monthly_peak_deficit: dict[int, int] = defaultdict(int)
        monthly_max_shortage_by_shift: dict[tuple[int, str], int] = defaultdict(int)
        monthly_required: dict[tuple[int, str], int] = defaultdict(int)
        monthly_scheduled: dict[tuple[int, str], int] = defaultdict(int)

        for day in calendar_dates:
            day_result = self._analyze_day(
                project,
                groups_by_shift,
                day,
            )

            coverage_by_day.append(day_result["day"])
            coverage_issues.extend(day_result["issues"])

            self._accumulate_monthly(
                day=day,
                shifts=day_result["day"]["shifts"],
                monthly_coverage_counts=monthly_coverage_counts,
                monthly_peak_deficit=monthly_peak_deficit,
                monthly_max_shortage_by_shift=monthly_max_shortage_by_shift,
                monthly_required=monthly_required,
                monthly_scheduled=monthly_scheduled,
            )

        return {
            "coverage_by_day": coverage_by_day,
            "coverage_issues": coverage_issues,
            "monthly_coverage_counts": monthly_coverage_counts,
            "monthly_peak_deficit": monthly_peak_deficit,
            "monthly_max_shortage_by_shift": monthly_max_shortage_by_shift,
            "monthly_required": monthly_required,
            "monthly_scheduled": monthly_scheduled,
        }

    @staticmethod
    def _group_by_shift(
        groups: list[ScheduleGroup],
    ) -> dict[str, list[ScheduleGroup]]:
        result: dict[str, list[ScheduleGroup]] = defaultdict(list)

        for group in groups:
            for shift_id in group.allocations or {group.shift_id}:
                result[shift_id].append(group)

        return result

    def _analyze_day(
        self,
        project: ProjectState,
        groups_by_shift: dict[str, list[ScheduleGroup]],
        day: date,
    ) -> DayCoverageResult:
        day_shifts: list[ShiftCoverage] = []
        issues: list[AnalysisIssue] = []

        total_required = 0
        total_scheduled = 0
        total_deficit = 0

        for shift in project.shifts:
            scheduled = sum(
                group.staff_for(shift.id)
                for group in groups_by_shift.get(shift.id, [])
                if ScheduleCalendar.works_shift(group, shift.id, day)
            )

            scheduled_hours = sum(
                group.staff_for(shift.id) * ScheduleCalendar.work_hours(group, shift, day)
                for group in groups_by_shift.get(shift.id, [])
                if ScheduleCalendar.works_shift(group, shift.id, day)
            )
            required = shift.demand_by_date.get(
                day.isoformat(), shift.demand_by_weekday[day.weekday()]
            )
            deficit = max(0, required - scheduled)
            surplus = max(0, scheduled - required)

            item: ShiftCoverage = {
                "shift_id": shift.id,
                "shift_name": shift.name,
                "required": required,
                "scheduled": scheduled,
                "deficit": deficit,
                "surplus": surplus,
                "required_work_hours": round(required * shift.work_hours, 4),
                "scheduled_work_hours": round(scheduled_hours, 4),
                "deficit_work_hours": round(
                    max(0, required * shift.work_hours - scheduled_hours), 4
                ),
            }

            if item["deficit_work_hours"] > 1e-6 and not deficit:
                issues.append(
                    {
                        "code": "coverage-hours-gap",
                        "severity": "operational",
                        "date": day.isoformat(),
                        "month": day.month,
                        "title": "Horas de trabalho abaixo da demanda",
                        "message": f"{shift.name}: faltam {item['deficit_work_hours']:g} horas-pessoa; "
                        f"há {scheduled} pessoa(s), mas as jornadas não somam as horas requeridas.",
                        **item,
                    }
                )
            day_shifts.append(item)

            total_required += required
            total_scheduled += scheduled
            total_deficit += deficit

            if deficit:
                issues.append(
                    {
                        "code": "coverage-gap",
                        "severity": "operational",
                        "date": day.isoformat(),
                        "month": day.month,
                        "title": "Cobertura abaixo da demanda",
                        "message": (
                            f"{shift.name}: faltam {deficit} pessoa(s); "
                            f"demanda {required}, escala {scheduled}."
                        ),
                        **item,
                    }
                )

        return {
            "day": {
                "date": day.isoformat(),
                "weekday": day.weekday(),
                "day": day.day,
                "month": day.month,
                "is_sunday": day.weekday() == 6,
                "total_required": total_required,
                "total_scheduled": total_scheduled,
                "total_deficit": total_deficit,
                "shifts": day_shifts,
            },
            "issues": issues,
        }

    @staticmethod
    def _accumulate_monthly(
        day: date,
        shifts: list[ShiftCoverage],
        monthly_coverage_counts: dict[int, int],
        monthly_peak_deficit: dict[int, int],
        monthly_max_shortage_by_shift: dict[tuple[int, str], int],
        monthly_required: dict[tuple[int, str], int],
        monthly_scheduled: dict[tuple[int, str], int],
    ) -> None:
        for shift in shifts:
            shift_id = shift["shift_id"]
            deficit = shift["deficit"]

            monthly_required[(day.month, shift_id)] += shift["required"]
            monthly_scheduled[(day.month, shift_id)] += shift["scheduled"]

            monthly_max_shortage_by_shift[(day.month, shift_id)] = max(
                monthly_max_shortage_by_shift[(day.month, shift_id)],
                deficit,
            )

            if deficit or shift["deficit_work_hours"] > 1e-6:
                monthly_coverage_counts[day.month] += 1
                monthly_peak_deficit[day.month] = max(
                    monthly_peak_deficit[day.month],
                    deficit,
                )
