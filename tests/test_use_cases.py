from datetime import date

from escala_analyzer.application.use_cases.load_project import LoadProject
from escala_analyzer.application.use_cases.reset_project import ResetProject
from escala_analyzer.application.use_cases.save_project import SaveProject
from escala_analyzer.domain.entities import ProjectState, ScheduleGroup, Shift


class FakeProjectRepository:
    def __init__(self) -> None:
        self.project = self._make_project()
        self.save_calls = 0
        self.reset_calls = 0

    @staticmethod
    def _make_project() -> ProjectState:
        return ProjectState(
            name="Projeto de teste",
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
        self.save_calls += 1

    def reset(self) -> ProjectState:
        self.project = self._make_project()
        self.reset_calls += 1
        return self.project


def test_load_project_returns_repository_state() -> None:
    repository = FakeProjectRepository()

    result = LoadProject(repository).execute()

    assert result is repository.project
    assert result.name == "Projeto de teste"


def test_save_project_persists_project() -> None:
    repository = FakeProjectRepository()
    project = repository._make_project()
    project.name = "Projeto atualizado"

    result = SaveProject(repository).execute(project)

    assert result is project
    assert repository.project.name == "Projeto atualizado"
    assert repository.save_calls == 1


def test_reset_project_restores_default_state() -> None:
    repository = FakeProjectRepository()
    repository.project.name = "Projeto alterado"

    result = ResetProject(repository).execute()

    assert result.name == "Projeto de teste"
    assert repository.reset_calls == 1
