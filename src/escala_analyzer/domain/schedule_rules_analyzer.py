
"""Validação das regras configuradas para os grupos de trabalho."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, ClassVar

from .models import ProjectState, Shift
from .schedule_calendar import ScheduleCalendar


class ScheduleRulesAnalyzer:
    """Analisa folgas, domingos, jornadas móveis e sequências de trabalho."""

    MONTH_NAMES: ClassVar[list[str]] = [
        "Janeiro",
        "Fevereiro",
        "Março",
        "Abril",
        "Maio",
        "Junho",
        "Julho",
        "Agosto",
        "Setembro",
        "Outubro",
        "Novembro",
        "Dezembro",
    ]

    def analyze(
        self,
        project: ProjectState,
        year_start: date,
        year_end: date,
        shifts: dict[str, Shift],
    ) -> dict[str, list[dict[str, Any]]]:
        group_monthly: list[dict[str, Any]] = []
        rule_issues: list[dict[str, Any]] = []

        self._analyze_monthly_rest(
            project, shifts, group_monthly, rule_issues
        )
        self._analyze_rolling_windows(
            project, year_start, year_end, shifts, rule_issues
        )
        self._analyze_consecutive_work(
            project, year_start, year_end, shifts, rule_issues
        )

        return {
            "group_monthly": group_monthly,
            "rule_issues": rule_issues,
        }

    def _analyze_monthly_rest(
        self,
        project: ProjectState,
        shifts: dict[str, Shift],
        group_monthly: list[dict[str, Any]],
        rule_issues: list[dict[str, Any]],
    ) -> None:
        for group in project.groups:
            shift = shifts[group.shift_id]

            for month in range(1, 13):
                month_days = ScheduleCalendar.month_dates(project.year, month)
                off_days = [
                    day
                    for day in month_days
                    if not ScheduleCalendar.is_working(group, day)
                ]
                sunday_offs = [
                    day for day in off_days if day.weekday() == 6
                ]

                group_monthly.append(
                    {
                        "group_id": group.id,
                        "group_name": group.name,
                        "shift_id": group.shift_id,
                        "shift_name": shift.name,
                        "month": month,
                        "month_name": self.MONTH_NAMES[month - 1],
                        "employees": group.employee_count,
                        "days_off": len(off_days),
                        "sundays_off": len(sunday_offs),
                        "sunday_dates_off": [
                            day.isoformat() for day in sunday_offs
                        ],
                    }
                )

                if (
                    project.rules.check_min_days_off_per_month
                    and len(off_days) < project.rules.min_days_off_per_month
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
                                f"{self.MONTH_NAMES[month - 1]}; o parâmetro "
                                f"configurado é "
                                f"{project.rules.min_days_off_per_month}."
                            ),
                            "actual": len(off_days),
                            "expected": project.rules.min_days_off_per_month,
                        }
                    )

                if len(sunday_offs) < project.rules.min_sundays_off_per_month:
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
                                f"{self.MONTH_NAMES[month - 1]}; o parâmetro "
                                f"configurado é "
                                f"{project.rules.min_sundays_off_per_month}."
                            ),
                            "actual": len(sunday_offs),
                            "expected": project.rules.min_sundays_off_per_month,
                        }
                    )

    def _analyze_rolling_windows(
        self,
        project: ProjectState,
        year_start: date,
        year_end: date,
        shifts: dict[str, Shift],
        rule_issues: list[dict[str, Any]],
    ) -> None:
        window_issue_counts: dict[
            tuple[str, str, int], dict[str, Any]
        ] = {}

        window_start = year_start - timedelta(days=6)

        for group in project.groups:
            shift = shifts[group.shift_id]
            day = window_start

            while day <= year_end:
                window = [
                    day + timedelta(days=offset)
                    for offset in range(7)
                ]

                if not any(
                    year_start <= item <= year_end for item in window
                ):
                    day += timedelta(days=1)
                    continue

                working_days = [
                    item
                    for item in window
                    if ScheduleCalendar.is_working(group, item)
                ]
                rest_count = 7 - len(working_days)
                weekly_hours = len(working_days) * shift.hours_per_day

                failures: list[tuple[str, str]] = []

                if rest_count < project.rules.min_rest_days_in_rolling_7:
                    failures.append(
                        (
                            "rolling-rest",
                            (
                                f"{rest_count} dia(s) de descanso em uma janela "
                                f"de 7 dias; parâmetro: "
                                f"{project.rules.min_rest_days_in_rolling_7}."
                            ),
                        )
                    )

                if (
                    weekly_hours
                    > project.rules.weekly_max_hours + 1e-9
                ):
                    failures.append(
                        (
                            "rolling-hours",
                            (
                                f"{weekly_hours:g} h em uma janela de 7 dias; "
                                f"limite configurado: "
                                f"{project.rules.weekly_max_hours:g} h."
                            ),
                        )
                    )

                touched_months = sorted(
                    {
                        item.month
                        for item in window
                        if year_start <= item <= year_end
                    }
                )

                for code, detail in failures:
                    for month in touched_months:
                        key = (group.id, code, month)
                        record = window_issue_counts.get(key)

                        if record is None:
                            record = {
                                "code": code,
                                "severity": "rule",
                                "month": month,
                                "group_id": group.id,
                                "group_name": group.name,
                                "shift_name": shift.name,
                                "title": (
                                    "Descanso insuficiente em janela móvel "
                                    "de 7 dias"
                                    if code == "rolling-rest"
                                    else "Jornada semanal acima do parâmetro"
                                ),
                                "message": detail,
                                "windows_count": 0,
                                "first_window_start": day.isoformat(),
                                "last_window_start": day.isoformat(),
                            }
                            window_issue_counts[key] = record

                        record["windows_count"] += 1
                        record["last_window_start"] = day.isoformat()

                day += timedelta(days=1)

        for item in window_issue_counts.values():
            item["message"] = (
                f"{item['message']} Ocorrências em "
                f"{self.MONTH_NAMES[item['month'] - 1]}: "
                f"{item['windows_count']} janela(s); primeira janela "
                f"iniciada em {item['first_window_start']}."
            )
            rule_issues.append(item)

    def _analyze_consecutive_work(
        self,
        project: ProjectState,
        year_start: date,
        year_end: date,
        shifts: dict[str, Shift],
        rule_issues: list[dict[str, Any]],
    ) -> None:
        for group in project.groups:
            shift = shifts[group.shift_id]
            scan_start = year_start - timedelta(days=31)

            streak_start: date | None = None
            streak_length = 0
            day = scan_start

            while day <= year_end + timedelta(days=1):
                working = (
                    day <= year_end
                    and ScheduleCalendar.is_working(group, day)
                )

                if working:
                    if streak_length == 0:
                        streak_start = day

                    streak_length += 1
                else:
                    if (
                        streak_length
                        > project.rules.max_consecutive_work_days
                        and streak_start is not None
                    ):
                        first_over_limit = streak_start + timedelta(
                            days=project.rules.max_consecutive_work_days
                        )

                        if first_over_limit <= year_end and day >= year_start:
                            month = max(
                                1, min(12, first_over_limit.month)
                            )

                            rule_issues.append(
                                {
                                    "code": "consecutive-work",
                                    "severity": "rule",
                                    "month": month,
                                    "group_id": group.id,
                                    "group_name": group.name,
                                    "shift_name": shift.name,
                                    "title": (
                                        "Sequência de trabalho acima "
                                        "do parâmetro"
                                    ),
                                    "message": (
                                        f"{group.name} ({shift.name}) "
                                        f"trabalhou {streak_length} dias "
                                        f"seguidos; o máximo configurado é "
                                        f"{project.rules.max_consecutive_work_days}."
                                    ),
                                    "actual": streak_length,
                                    "expected": (
                                        project.rules.max_consecutive_work_days
                                    ),
                                    "date": first_over_limit.isoformat(),
                                }
                            )

                    streak_start = None
                    streak_length = 0

                day += timedelta(days=1)
