from escala_analyzer.application.ports.project_repository import ProjectRepository
from escala_analyzer.domain.models import ProjectState


class ResetProject:
    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    def execute(self) -> ProjectState:
        return self._repository.reset()