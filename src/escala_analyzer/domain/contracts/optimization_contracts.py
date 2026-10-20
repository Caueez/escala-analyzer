"""Explicit contracts shared by optimization services and their callers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict

from escala_analyzer.domain.contracts.analysis_contracts import AnalysisIssue
from escala_analyzer.domain.contracts.types import JsonValue
from escala_analyzer.domain.entities import OptimizationPriority, ScheduleGroup

PatternKey = tuple[tuple[int, ...], int]


@dataclass(frozen=True, slots=True)
class CandidatePattern:
    group: ScheduleGroup
    working_days: list[bool]
    rule_issue_count: int


ProposalSignature = tuple[
    tuple[str, tuple[int, ...], int, tuple[tuple[str, int], ...], tuple[float | None, ...]], ...
]


class SearchStage(TypedDict):
    objective: str
    status: NotRequired[str]
    seconds: NotRequired[float]
    value: NotRequired[int]
    optimal: NotRequired[bool]


class HoursOptimizationReport(TypedDict):
    status: Literal["unchanged", "invalid_bounds", "no_solution", "optimized", "timeout"]
    groups: list[str]
    message: NotRequired[str]
    stages: NotRequired[list[SearchStage]]
    scope: NotRequired[str]


class BusinessMetrics(TypedDict):
    pattern_count: int
    monthly_staff_cost: float


class OptimizationMetrics(BusinessMetrics):
    rule_violation_count: int
    limit_violation_count: int
    group_count: int
    people_total: int
    deficit_staff_days: int
    surplus_staff_days: int
    added_group_count: int
    deficit_work_hours: float


class GroupChange(TypedDict):
    group_id: str
    group_name: str
    before: dict[str, JsonValue]
    after: dict[str, JsonValue]


class HourChange(TypedDict):
    group_id: str
    group_name: str
    before: list[float | None]
    after: list[float | None]


class OptimizationSolution(TypedDict):
    id: str
    baseline: bool
    business_acceptable: bool
    hours_optimization: HoursOptimizationReport | None
    group_changes: list[GroupChange]
    hour_changes: list[HourChange]
    label: str
    project: dict[str, JsonValue]
    metrics: OptimizationMetrics
    issues: list[AnalysisIssue]
    ranking: list[int | float]
    optimal: bool
    stages: list[SearchStage]


class OptimizationResult(TypedDict):
    status: Literal["partial", "feasible", "timeout"]
    project: dict[str, JsonValue]
    metrics: OptimizationMetrics
    solutions: list[OptimizationSolution]
    optimal: bool
    search_complete: bool
    solutions_found: int
    solution_limit: int
    truncated: bool
    stages: list[SearchStage]
    warnings: list[str]
    priorities: list[OptimizationPriority]
    scope: str
    rejected_patterns: list[str]
    candidate_cycle_count: int
    max_cycle_days: int | None
    elapsed_seconds: float
    message: str
