"""Typed reports for coverage, schedule rules and consolidated analysis."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from escala_analyzer.domain.contracts.types import JsonValue


class AnalysisIssue(TypedDict):
    code: str
    severity: Literal["rule", "operational"]
    title: str
    message: str
    month: NotRequired[int]
    date: NotRequired[str]
    group_id: NotRequired[str]
    group_name: NotRequired[str]
    shift_id: NotRequired[str]
    shift_name: NotRequired[str]
    actual: NotRequired[int | float | None]
    expected: NotRequired[int | float | None]
    deficit: NotRequired[int]
    surplus: NotRequired[int]
    required: NotRequired[int]
    scheduled: NotRequired[int]
    required_work_hours: NotRequired[float]
    scheduled_work_hours: NotRequired[float]
    deficit_work_hours: NotRequired[float]
    windows_count: NotRequired[int]
    first_window_start: NotRequired[str]
    last_window_start: NotRequired[str]
    occurrences_count: NotRequired[int]
    last_date: NotRequired[str]
    configuration_section: NotRequired[str]


class ShiftCoverage(TypedDict):
    shift_id: str
    shift_name: str
    required: int
    scheduled: int
    deficit: int
    surplus: int
    required_work_hours: float
    scheduled_work_hours: float
    deficit_work_hours: float


class DayCoverage(TypedDict):
    date: str
    weekday: int
    day: int
    month: int
    is_sunday: bool
    total_required: int
    total_scheduled: int
    total_deficit: int
    shifts: list[ShiftCoverage]


class DayCoverageResult(TypedDict):
    day: DayCoverage
    issues: list[AnalysisIssue]


class CoverageResult(TypedDict):
    coverage_by_day: list[DayCoverage]
    coverage_issues: list[AnalysisIssue]
    monthly_coverage_counts: dict[int, int]
    monthly_peak_deficit: dict[int, int]
    monthly_max_shortage_by_shift: dict[tuple[int, str], int]
    monthly_required: dict[tuple[int, str], int]
    monthly_scheduled: dict[tuple[int, str], int]


class Journey(TypedDict):
    date: str
    shift_id: str
    shift_name: str
    start: str | None
    end: str | None
    work_hours: float
    break_minutes: int
    rest_before_hours: float | None


class PeriodHours(TypedDict, total=False):
    work_days: int
    work_hours: float
    break_hours: float
    rest_hours: float
    min_intershift_hours: float | None
    max_intershift_hours: float | None
    timing_complete: bool


class AllocationDetails(PeriodHours):
    shift_id: str | None
    shift_name: str
    employees: int
    journeys: list[Journey]


class GroupPeriodDetails(PeriodHours):
    group_id: str
    group_name: str
    days_off: int
    days_off_by_weekday: list[int]
    sundays_off: int
    hours_basis: str
    allocations: list[AllocationDetails]


class GroupMonthlyDetails(PeriodHours):
    group_id: str
    group_name: str
    shift_id: str
    shift_name: str
    month: int
    month_name: str
    employees: int
    days_off: int
    sundays_off: int
    sunday_dates_off: list[str]
    days_off_by_weekday: NotRequired[list[int]]
    hours_basis: NotRequired[str]
    allocations: NotRequired[list[AllocationDetails]]


class RulesResult(TypedDict):
    group_annual: list[GroupPeriodDetails]
    group_monthly: list[GroupMonthlyDetails]
    rule_issues: list[AnalysisIssue]


class MonthlyShiftSummary(TypedDict):
    shift_id: str
    shift_name: str
    required_staff_days: int
    scheduled_staff_days: int
    max_daily_deficit: int


class MonthlySummary(TypedDict):
    month: int
    month_name: str
    coverage_gap_count: int
    worst_single_shift_deficit: int
    shifts: list[MonthlyShiftSummary]


class ProjectAnalysis(TypedDict):
    year: int
    days_in_year: int
    people_total: int
    group_count: int
    shift_count: int
    coverage_gap_count: int
    days_with_any_coverage_gap: int
    peak_single_shift_deficit: int
    rule_issue_count: int
    months_with_issues: list[int]
    rules: dict[str, JsonValue]
    rule_periods: list[dict[str, JsonValue]]
    coverage_by_day: list[DayCoverage]
    coverage_issues: list[AnalysisIssue]
    group_monthly: list[GroupMonthlyDetails]
    group_annual: list[GroupPeriodDetails]
    monthly_summary: list[MonthlySummary]
    rule_issues: list[AnalysisIssue]
    issues: list[AnalysisIssue]
    is_legal_opinion: bool
    disclaimer: str
