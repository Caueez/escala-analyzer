
"""Caso de uso para análise de um projeto de escala."""

from typing import Any

from escala_analyzer.domain.coverage_analyzer import CoverageAnalyzer
from escala_analyzer.domain.models import ProjectState
from escala_analyzer.domain.project_analyzer import ProjectAnalyzer
from escala_analyzer.domain.schedule_rules_analyzer import ScheduleRulesAnalyzer


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

    def execute(self, project: ProjectState) -> dict[str, Any]:
        return self._analyzer.analyze(project)
