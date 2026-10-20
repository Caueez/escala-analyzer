"""ConsecutiveWorkAnalyzer responsibility for schedule rule analysis."""

from __future__ import annotations

from datetime import date, timedelta

from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.contracts.analysis_contracts import (
    AnalysisIssue,
)
from escala_analyzer.domain.entities import ProjectState, Shift
from escala_analyzer.domain.rules.rule_context import RuleContext


class ConsecutiveWorkAnalyzer:
    def analyze(
        self,
        project: ProjectState,
        year_start: date,
        year_end: date,
        shifts: dict[str, Shift],
        rule_issues: list[AnalysisIssue],
    ) -> None:
        for group in project.groups:
            streak = 0
            last_month = None
            day = year_start - timedelta(days=62)
            while day <= year_end:
                streak = streak + 1 if ScheduleCalendar.is_working(group, day) else 0
                rules = project.rules_on(day)
                if day >= year_start and streak > rules.max_consecutive_work_days:
                    if last_month != day.month:
                        rule_issues.append(
                            {
                                "code": "consecutive-work",
                                "severity": "rule",
                                "month": day.month,
                                "group_id": group.id,
                                "group_name": group.name,
                                "shift_name": RuleContext.strictest_shift(group, shifts).name,
                                "title": "Sequência de trabalho acima do parâmetro",
                                "message": f"{group.name}: {streak} dias seguidos; máximo {rules.max_consecutive_work_days}.",
                                "actual": streak,
                                "expected": rules.max_consecutive_work_days,
                                "date": day.isoformat(),
                            }
                        )
                        last_month = day.month
                elif streak == 0:
                    last_month = None
                day += timedelta(days=1)
