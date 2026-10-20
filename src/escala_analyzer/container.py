"""Composição das dependências da aplicação."""

from escala_analyzer.application.ports.project_repository import ProjectRepository
from escala_analyzer.application.use_cases.analyze_project import AnalyzeProject
from escala_analyzer.application.use_cases.load_project import LoadProject
from escala_analyzer.application.use_cases.optimize_schedule import OptimizeSchedule
from escala_analyzer.application.use_cases.reset_project import ResetProject
from escala_analyzer.application.use_cases.save_project import SaveProject
from escala_analyzer.domain.analysis.coverage_analyzer import CoverageAnalyzer
from escala_analyzer.domain.analysis.schedule_rules_analyzer import ScheduleRulesAnalyzer
from escala_analyzer.infrastructure.json_repository import JsonProjectRepository
from escala_analyzer.infrastructure.optimization.schedule_optimizer import ScheduleOptimizer


class ApplicationContainer:
    """Constrói e conecta as dependências da aplicação."""

    def __init__(
        self,
        repository: ProjectRepository | None = None,
        coverage_analyzer: CoverageAnalyzer | None = None,
        rules_analyzer: ScheduleRulesAnalyzer | None = None,
    ) -> None:
        self.repository = repository or JsonProjectRepository()

        self.optimize_schedule = OptimizeSchedule(ScheduleOptimizer())
        self.load_project = LoadProject(self.repository)
        self.save_project = SaveProject(self.repository)
        self.reset_project = ResetProject(self.repository)

        self.analyze_project = AnalyzeProject(
            coverage_analyzer=coverage_analyzer,
            rules_analyzer=rules_analyzer,
        )


container = ApplicationContainer()
