"""Search a proposal through the configured optimization provider."""

from escala_analyzer.application.ports.schedule_optimizer import ScheduleOptimizerPort
from escala_analyzer.domain.contracts.optimization_contracts import OptimizationResult
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.domain.optimization.optimization_options import OptimizationOptions


class OptimizeSchedule:
    def __init__(self, optimizer: ScheduleOptimizerPort) -> None:
        self._optimizer = optimizer

    def execute(self, project: ProjectState, options: OptimizationOptions) -> OptimizationResult:
        return self._optimizer.optimize(project, options)
