"""MonthlyRestAnalyzer responsibility for schedule rule analysis."""

from __future__ import annotations

from dataclasses import replace

from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.contracts.analysis_contracts import (
    AnalysisIssue,
    GroupMonthlyDetails,
)
from escala_analyzer.domain.entities import ProjectState, Shift
from escala_analyzer.domain.rules.rule_context import RuleContext


class MonthlyRestAnalyzer:
    def analyze(
        self,
        project: ProjectState,
        shifts: dict[str, Shift],
        group_monthly: list[GroupMonthlyDetails],
        rule_issues: list[AnalysisIssue],
    ) -> None:
        for group in project.groups:
            shift = RuleContext.strictest_shift(group, shifts)

            for month in range(1, 13):
                month_days = ScheduleCalendar.month_dates(project.year, month)
                # Monthly minima apply if active on any date in the month.
                active_rules = [project.rules_on(day) for day in month_days]
                rules = replace(
                    project.rules_on(month_days[-1]),
                    min_days_off_per_month=max(
                        r.min_days_off_per_month if r.check_min_days_off_per_month else 0
                        for r in active_rules
                    ),
                    check_min_days_off_per_month=any(
                        r.check_min_days_off_per_month for r in active_rules
                    ),
                    min_sundays_off_per_month=max(
                        r.min_sundays_off_per_month for r in active_rules
                    ),
                )
                off_days = [
                    day for day in month_days if not ScheduleCalendar.is_working(group, day)
                ]
                sunday_offs = [day for day in off_days if day.weekday() == 6]

                group_monthly.append(
                    {
                        "group_id": group.id,
                        "group_name": group.name,
                        "shift_id": group.shift_id,
                        "shift_name": shift.name,
                        "month": month,
                        "month_name": RuleContext.MONTH_NAMES[month - 1],
                        "employees": group.employee_count,
                        "days_off": len(off_days),
                        "sundays_off": len(sunday_offs),
                        "sunday_dates_off": [day.isoformat() for day in sunday_offs],
                    }
                )

                if (
                    rules.check_min_days_off_per_month
                    and len(off_days) < rules.min_days_off_per_month
                ):
                    rule_issues.append(
                        {
                            "code": "monthly-rest-days",
                            "severity": "rule",
                            "month": month,
                            "group_id": group.id,
                            "group_name": group.name,
                            "shift_name": shift.name,
                            "title": "Descansos mensais abaixo do parâmetro",
                            "message": (
                                f"{group.name} ({shift.name}) tem "
                                f"{len(off_days)} dia(s) de folga em "
                                f"{RuleContext.MONTH_NAMES[month - 1]}; o parâmetro "
                                f"configurado é "
                                f"{rules.min_days_off_per_month}."
                            ),
                            "actual": len(off_days),
                            "expected": rules.min_days_off_per_month,
                        }
                    )

                if len(sunday_offs) < rules.min_sundays_off_per_month:
                    rule_issues.append(
                        {
                            "code": "monthly-sunday-rest",
                            "severity": "rule",
                            "month": month,
                            "group_id": group.id,
                            "group_name": group.name,
                            "shift_name": shift.name,
                            "title": "Domingos de folga abaixo do parâmetro",
                            "message": (
                                f"{group.name} ({shift.name}) tem "
                                f"{len(sunday_offs)} domingo(s) de folga em "
                                f"{RuleContext.MONTH_NAMES[month - 1]}; o parâmetro "
                                f"configurado é "
                                f"{rules.min_sundays_off_per_month}."
                            ),
                            "actual": len(sunday_offs),
                            "expected": rules.min_sundays_off_per_month,
                        }
                    )
