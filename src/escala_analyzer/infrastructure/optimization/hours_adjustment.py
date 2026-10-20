"""Apply the optional hours adjustment within the shared search deadline."""

from __future__ import annotations

from time import monotonic

from escala_analyzer.domain.contracts.optimization_contracts import HoursOptimizationReport
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.domain.optimization.optimization_options import OptimizationOptions
from escala_analyzer.infrastructure.optimization.group_hours_optimizer import GroupHoursOptimizer


class HoursAdjustment:
    def __init__(self, options: OptimizationOptions, deadline: float, warnings: list[str]) -> None:
        self.options = options
        self.deadline = deadline
        self.warnings = warnings

    def fit(self, proposal: ProjectState) -> tuple[ProjectState, HoursOptimizationReport | None]:
        remaining = self.deadline - monotonic()
        if not self.options.optimize_work_hours or remaining <= 0:
            return proposal, None
        adjusted, report = GroupHoursOptimizer().optimize(
            proposal, self.options.hours_step_minutes, min(5, remaining / 2)
        )
        if report["status"] not in {"optimized", "unchanged"}:
            message = report.get(
                "message",
                "O ajuste de horas foi limitado pelo tempo; confira as jornadas e os alertas da alternativa.",
            )
            if message not in self.warnings:
                self.warnings.append(message)
        return adjusted, report
