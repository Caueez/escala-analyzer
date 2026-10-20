"""RollingWindowAnalyzer responsibility for schedule rule analysis."""

from __future__ import annotations

from datetime import date, timedelta

from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.contracts.analysis_contracts import (
    AnalysisIssue,
)
from escala_analyzer.domain.entities import ProjectState, Shift
from escala_analyzer.domain.rules.rule_context import RuleContext


class RollingWindowAnalyzer:
    def analyze(
        self,
        project: ProjectState,
        year_start: date,
        year_end: date,
        shifts: dict[str, Shift],
        rule_issues: list[AnalysisIssue],
    ) -> None:
        window_issue_counts: dict[tuple[str, str, int], AnalysisIssue] = {}

        window_start = year_start - timedelta(days=6)

        for group in project.groups:
            shift = RuleContext.strictest_shift(group, shifts)
            day = window_start

            while day <= year_end:
                window = [day + timedelta(days=offset) for offset in range(7)]

                if not any(year_start <= item <= year_end for item in window):
                    day += timedelta(days=1)
                    continue

                rules = project.rules_on(window[-1])
                working_days = [item for item in window if ScheduleCalendar.is_working(group, item)]
                rest_count = 7 - len(working_days)
                weekly_hours = sum(
                    RuleContext.rotating_hours(group, item, shifts)
                    if group.rotation_shift_ids
                    else ScheduleCalendar.work_hours(group, shift, item)
                    for item in working_days
                )

                failures: list[tuple[str, str]] = []

                if rest_count < rules.min_rest_days_in_rolling_7:
                    failures.append(
                        (
                            "rolling-rest",
                            (
                                f"{rest_count} dia(s) de descanso em uma janela "
                                f"de 7 dias; parâmetro: "
                                f"{rules.min_rest_days_in_rolling_7}."
                            ),
                        )
                    )

                if weekly_hours > rules.weekly_max_hours + 1e-9:
                    failures.append(
                        (
                            "rolling-hours",
                            (
                                f"{weekly_hours:g} h em uma janela de 7 dias; "
                                f"limite configurado: "
                                f"{rules.weekly_max_hours:g} h."
                            ),
                        )
                    )

                touched_months = sorted(
                    {item.month for item in window if year_start <= item <= year_end}
                )

                for code, detail in failures:
                    for month in touched_months:
                        key = (group.id, code, month)
                        record: AnalysisIssue | None = window_issue_counts.get(key)

                        if record is None:
                            record = {
                                "code": code,
                                "severity": "rule",
                                "month": month,
                                "group_id": group.id,
                                "group_name": group.name,
                                "shift_name": shift.name,
                                "title": (
                                    "Descanso insuficiente em janela móvel de 7 dias"
                                    if code == "rolling-rest"
                                    else "Jornada semanal acima do parâmetro"
                                ),
                                "message": detail,
                                "windows_count": 0,
                                "first_window_start": day.isoformat(),
                                "last_window_start": day.isoformat(),
                            }
                            window_issue_counts[key] = record

                        record["windows_count"] = record.get("windows_count", 0) + 1
                        record["last_window_start"] = day.isoformat()

                day += timedelta(days=1)

        for item in window_issue_counts.values():
            item["message"] = (
                f"{item['message']} Ocorrências em "
                f"{RuleContext.MONTH_NAMES[item.get('month', 1) - 1]}: "
                f"{item.get('windows_count', 0)} janela(s); primeira janela "
                f"iniciada em {item.get('first_window_start', '')}."
            )
            rule_issues.append(item)
