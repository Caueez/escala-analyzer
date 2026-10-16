from typing import Protocol

from escala_analyzer.domain.models import ProjectState


class ProjectRepository(Protocol):
    def load(self) -> ProjectState: ...

    def save(self, project: ProjectState) -> None: ...

    def reset(self) -> ProjectState: ...