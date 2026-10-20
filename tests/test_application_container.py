from datetime import date

from escala_analyzer.application.use_cases.analyze_project import AnalyzeProject
from escala_analyzer.container import ApplicationContainer
from escala_analyzer.domain.analysis.coverage_analyzer import CoverageAnalyzer
from escala_analyzer.domain.analysis.schedule_rules_analyzer import ScheduleRulesAnalyzer
from escala_analyzer.domain.entities import ProjectState, ScheduleGroup, Shift


class FakeProjectRepository:
    def __init__(self) -> None:
        self.project = ProjectState(
            name="Teste",
            year=2026,
            selected_month=1,
            shifts=[
                Shift(
                    id="shift-1",
                    name="Manhã",
                    hours_per_day=8,
                    demand_by_weekday=[1, 1, 1, 1, 1, 1, 1],
                )
            ],
            groups=[
                ScheduleGroup(
                    id="group-1",
                    name="Grupo A",
                    shift_id="shift-1",
                    employee_count=5,
                    work_days=5,
                    rest_days=2,
                    cycle_anchor=date(2026, 1, 1),
                )
            ],
        )

    def load(self) -> ProjectState:
        return self.project

    def save(self, project: ProjectState) -> None:
        self.project = project

    def reset(self) -> ProjectState:
        return self.project


def test_container_uses_injected_repository() -> None:
    repository = FakeProjectRepository()

    container = ApplicationContainer(repository=repository)

    assert container.load_project.execute() is repository.project


def test_analyze_project_returns_expected_structure() -> None:
    project = FakeProjectRepository().load()

    use_case = AnalyzeProject(
        coverage_analyzer=CoverageAnalyzer(),
        rules_analyzer=ScheduleRulesAnalyzer(),
    )

    result = use_case.execute(project)

    expected_keys = {
        "year",
        "days_in_year",
        "people_total",
        "coverage_by_day",
        "coverage_issues",
        "group_monthly",
        "monthly_summary",
        "rule_issues",
        "issues",
        "is_legal_opinion",
        "disclaimer",
    }

    assert expected_keys.issubset(result.keys())
    assert result["year"] == 2026
    assert result["days_in_year"] == 365
    assert result["people_total"] == 5
    assert len(result["coverage_by_day"]) == 365
    assert len(result["group_monthly"]) == 12
