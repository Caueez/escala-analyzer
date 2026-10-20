from escala_analyzer.application.ports.project_repository import ProjectRepository
from escala_analyzer.domain.entities import ProjectState


class SaveProject:
    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    def execute(self, project: ProjectState) -> ProjectState:
        self._repository.save(project)
        return project
