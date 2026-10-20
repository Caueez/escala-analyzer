"""Orchestrate independent rule checks and optional period reports."""

from __future__ import annotations

from copy import deepcopy
from datetime import date

from escala_analyzer.domain.analysis.group_period_reporter import GroupPeriodReporter
from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.contracts.analysis_contracts import (
    AnalysisIssue,
    GroupMonthlyDetails,
    RulesResult,
)
from escala_analyzer.domain.entities import ProjectState, Shift
from escala_analyzer.domain.rules.consecutive_work_analyzer import ConsecutiveWorkAnalyzer
from escala_analyzer.domain.rules.journey_timing_analyzer import JourneyTimingAnalyzer
from escala_analyzer.domain.rules.monthly_rest_analyzer import MonthlyRestAnalyzer
from escala_analyzer.domain.rules.rolling_window_analyzer import RollingWindowAnalyzer
from escala_analyzer.domain.rules.rule_context import RuleContext


class ScheduleRulesAnalyzer:
    MONTH_NAMES = RuleContext.MONTH_NAMES

    def analyze(
        self,
        project: ProjectState,
        year_start: date,
        year_end: date,
        shifts: dict[str, Shift],
        include_details: bool = True,
    ) -> RulesResult:
        project = deepcopy(project)
        for group in project.groups:
            group.allocations = {
                sid: count for sid, count in group.allocations.items() if count > 0
            }
        project.groups = [g for g in project.groups if g.allocations]
        group_monthly: list[GroupMonthlyDetails] = []
        rule_issues: list[AnalysisIssue] = []

        JourneyTimingAnalyzer().analyze(project, year_start, year_end, shifts, rule_issues)

        MonthlyRestAnalyzer().analyze(project, shifts, group_monthly, rule_issues)
        RollingWindowAnalyzer().analyze(project, year_start, year_end, shifts, rule_issues)
        ConsecutiveWorkAnalyzer().analyze(project, year_start, year_end, shifts, rule_issues)

        for index, row in enumerate(group_monthly if include_details else []):
            group = next(g for g in project.groups if g.id == row["group_id"])
            details = GroupPeriodReporter().report(
                group, shifts, ScheduleCalendar.month_dates(project.year, row["month"])
            )
            group_monthly[index] = {**row, **details}

        return {
            "group_annual": [
                GroupPeriodReporter().report(g, shifts, ScheduleCalendar.year_dates(project.year))
                for g in project.groups
                if include_details
            ],
            "group_monthly": group_monthly,
            "rule_issues": rule_issues,
        }
