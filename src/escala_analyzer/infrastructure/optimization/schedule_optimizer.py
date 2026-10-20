"""Orchestrate schedule optimization without changing the saved project."""

from __future__ import annotations

from time import monotonic

from escala_analyzer.domain.analysis.project_analyzer import ProjectAnalyzer
from escala_analyzer.domain.contracts.optimization_contracts import OptimizationResult
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.domain.optimization.optimization_options import (
    OptimizationCycle,
    OptimizationOptions,
)
from escala_analyzer.infrastructure.optimization.complement_search import ComplementSearch
from escala_analyzer.infrastructure.optimization.existing_groups_optimizer import (
    ExistingGroupsOptimizer,
)
from escala_analyzer.infrastructure.optimization.hours_adjustment import HoursAdjustment
from escala_analyzer.infrastructure.optimization.optimization_results import (
    ADDITIONS_SCOPE,
    OptimizationResults,
)

__all__ = ["OptimizationCycle", "OptimizationOptions", "ScheduleOptimizer"]


class ScheduleOptimizer:
    SCOPE = ADDITIONS_SCOPE

    def __init__(self, analyzer: ProjectAnalyzer | None = None) -> None:
        self._analyzer = analyzer or ProjectAnalyzer()

    def optimize(
        self, project: ProjectState, options: OptimizationOptions | None = None
    ) -> OptimizationResult:
        options = options or OptimizationOptions()
        results = OptimizationResults(project, options, monotonic(), self._analyzer)
        hours = HoursAdjustment(options, results.deadline, results.warnings)
        results.retain(project, baseline=True)
        search_project = project
        if options.optimize_work_hours and not results.limited:
            search_project, report = hours.fit(project)
            results.retain(search_project, hour_report=report)
        if results.limited or monotonic() >= results.deadline:
            return results.result()
        if options.optimize_existing:
            pattern_deadline = results.deadline - max(0, results.deadline - monotonic()) * (
                0.3 if options.optimize_work_hours else 0
            )
            proposals, stages = ExistingGroupsOptimizer().optimize(
                search_project, options, pattern_deadline
            )
            results.stages.extend(stages)
            for proposal in proposals:
                adjusted, report = hours.fit(proposal)
                results.retain(adjusted, hour_report=report)
        else:
            ComplementSearch().search(project, search_project, options, results, hours)
        return results.result()
