"""Caso de uso para análise de um projeto de escala."""

from escala_analyzer.domain.analysis.coverage_analyzer import CoverageAnalyzer
from escala_analyzer.domain.analysis.project_analyzer import ProjectAnalyzer
from escala_analyzer.domain.analysis.schedule_rules_analyzer import ScheduleRulesAnalyzer
from escala_analyzer.domain.contracts.analysis_contracts import ProjectAnalysis
from escala_analyzer.domain.entities import ProjectState


class AnalyzeProject:
    """Executa a análise de um projeto usando os analisadores configurados."""

    def __init__(
        self,
        coverage_analyzer: CoverageAnalyzer | None = None,
        rules_analyzer: ScheduleRulesAnalyzer | None = None,
    ) -> None:
        self._analyzer = ProjectAnalyzer(
            coverage_analyzer=coverage_analyzer,
            rules_analyzer=rules_analyzer,
        )

    def execute(self, project: ProjectState) -> ProjectAnalysis:
        return self._analyzer.analyze(project)
