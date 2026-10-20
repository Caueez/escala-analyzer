"""Application port for a schedule proposal search."""

from typing import Protocol

from escala_analyzer.domain.contracts.optimization_contracts import OptimizationResult
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.domain.optimization.optimization_options import OptimizationOptions


class ScheduleOptimizerPort(Protocol):
    def optimize(
        self, project: ProjectState, options: OptimizationOptions
    ) -> OptimizationResult: ...
