"""Project transport preserves the editor's format and requires revision guards."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from escala_analyzer.api.dependencies import Access
from escala_analyzer.application.services.identity import Principal
from escala_analyzer.application.services.job_policy import JobPolicy
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.infrastructure.database.project_repository import SqlProjectRepository
from escala_analyzer.infrastructure.schemas.project import ProjectState as ProjectSchema
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec

router = APIRouter(prefix="/api", tags=["projects"])


class BackupInput(BaseModel):
    schema_version: int = 2
    active_id: str
    projects: list[ProjectSchema] = Field(min_length=1, max_length=100)


class ReuseInput(BaseModel):
    source_project_id: str
    group_id: str
    linked: bool = False


@router.get("/projects")
def list_projects(
    repository: Annotated[SqlProjectRepository, Depends(Access.repository)],
) -> list[dict]:
    return [EntityCodec.dump(project, mode="json") for project, _ in repository.list_projects()]


@router.get("/project")
def load(
    response: Response, repository: Annotated[SqlProjectRepository, Depends(Access.repository)]
) -> dict:
    project, revision = repository.load()
    response.headers["ETag"] = f'"{revision}"'
    return EntityCodec.dump(project, mode="json")


@router.get("/projects/{project_id}")
def load_by_id(
    project_id: str,
    response: Response,
    repository: Annotated[SqlProjectRepository, Depends(Access.repository)],
) -> dict:
    project, revision = repository.load(project_id)
    response.headers["ETag"] = f'"{revision}"'
    return EntityCodec.dump(project, mode="json")


@router.put("/project")
def save(
    payload: ProjectSchema,
    response: Response,
    principal: Annotated[Principal, Depends(Access.editor)],
    revision: Annotated[int, Depends(Access.revision)],
    repository: Annotated[SqlProjectRepository, Depends(Access.repository)],
) -> dict:
    project = EntityCodec.to_domain(payload)
    JobPolicy.validate(project)
    project.shared_group_links = {
        gid: link
        for gid, link in project.shared_group_links.items()
        if gid in {group.id for group in project.groups}
    }
    updated = repository.save(project, revision)
    response.headers["ETag"] = f'"{updated}"'
    return EntityCodec.dump(project, mode="json")


@router.post("/project/reset")
def reset(
    response: Response,
    principal: Annotated[Principal, Depends(Access.editor)],
    revision: Annotated[int, Depends(Access.revision)],
    repository: Annotated[SqlProjectRepository, Depends(Access.repository)],
) -> dict:
    current, _ = repository.load()
    project = ProjectState(
        project_id=current.project_id,
        portfolio_id=current.portfolio_id,
        portfolio_name=current.portfolio_name,
    )
    updated = repository.save(project, revision)
    response.headers["ETag"] = f'"{updated}"'
    return EntityCodec.dump(project, mode="json")


@router.delete("/projects/{project_id}")
def delete(
    project_id: str,
    principal: Annotated[Principal, Depends(Access.editor)],
    revision: Annotated[int, Depends(Access.revision)],
    repository: Annotated[SqlProjectRepository, Depends(Access.repository)],
) -> dict[str, str]:
    repository.delete(project_id, revision)
    return {"status": "ok"}


@router.post("/projects/import")
def import_backup(
    payload: BackupInput,
    response: Response,
    principal: Annotated[Principal, Depends(Access.editor)],
    repository: Annotated[SqlProjectRepository, Depends(Access.repository)],
) -> dict:
    projects = [EntityCodec.to_domain(project) for project in payload.projects]
    for project in projects:
        JobPolicy.validate(project)
    repository.import_projects(projects, payload.active_id)
    return load(response, repository)


@router.post("/projects/{project_id}/reuse-group")
def reuse(
    project_id: str,
    payload: ReuseInput,
    response: Response,
    principal: Annotated[Principal, Depends(Access.editor)],
    revision: Annotated[int, Depends(Access.revision)],
    repository: Annotated[SqlProjectRepository, Depends(Access.repository)],
) -> dict:
    target, updated = repository.reuse(
        project_id, payload.source_project_id, payload.group_id, payload.linked, revision
    )
    response.headers["ETag"] = f'"{updated}"'
    return EntityCodec.dump(target, mode="json")
