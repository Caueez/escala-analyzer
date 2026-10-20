"""Ponto de entrada da aplicação web local Escala Visual."""

from __future__ import annotations

import csv
import io
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from escala_analyzer.container import container
from escala_analyzer.domain.contracts.analysis_contracts import ProjectAnalysis
from escala_analyzer.domain.contracts.optimization_contracts import OptimizationResult
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.infrastructure.json_repository import JsonProjectRepository
from escala_analyzer.infrastructure.schemas.optimization import OptimizationRequest
from escala_analyzer.infrastructure.schemas.project import ProjectState as ProjectSchema
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec

WEB_DIR = Path(__file__).parents[1] / "web"

app = FastAPI(
    title="Escala Visual",
    version="0.1.0",
    description="Editor local de escalas com linha do tempo e análise anual configurável.",
)

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "application": "escala-visual"}


@app.get("/api/project", response_model=ProjectSchema)
def get_project() -> ProjectState:
    try:
        return container.load_project.execute()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/projects", response_model=list[ProjectSchema])
def list_projects() -> list[ProjectState]:
    return container.repository.list_projects()  # type: ignore[attr-defined]


class ProjectsBackup(BaseModel):
    schema_version: int = 2
    active_id: str
    projects: list[ProjectSchema] = Field(min_length=1)


@app.post("/api/projects/import", response_model=ProjectSchema)
def import_projects(backup: ProjectsBackup) -> ProjectState:
    projects = [EntityCodec.to_domain(p) for p in backup.projects]
    ids = [p.project_id for p in projects]
    if len(ids) != len(set(ids)) or backup.active_id not in ids:
        raise HTTPException(status_code=422, detail="Identificadores inválidos no backup.")
    active = next(p for p in projects if p.project_id == backup.active_id)
    repository = cast(JsonProjectRepository, container.repository)
    try:
        repository.save(active, related=[p for p in projects if p != active])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return active


@app.get("/api/projects/{project_id}", response_model=ProjectSchema)
def get_project_by_id(project_id: str) -> ProjectState:
    try:
        return container.repository.load_by_id(project_id)  # type: ignore[attr-defined]
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.") from exc


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, str]:
    try:
        container.repository.delete(project_id)  # type: ignore[attr-defined]
        return {"status": "ok"}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ReuseGroupRequest(BaseModel):
    source_project_id: str
    group_id: str
    linked: bool = False


@app.post("/api/projects/{project_id}/reuse-group", response_model=ProjectSchema)
def reuse_group(project_id: str, request: ReuseGroupRequest) -> ProjectState:
    repository = cast(JsonProjectRepository, container.repository)
    try:
        source = repository.load_by_id(request.source_project_id)
        target = repository.load_by_id(project_id)
        group = next(g for g in source.groups if g.id == request.group_id)
        needed = set(group.allocations) | set(group.rotation_shift_ids)
        for shift in source.shifts:
            if shift.id not in needed:
                continue
            existing = next((s for s in target.shifts if s.id == shift.id), None)
            if existing is not None and existing != shift:
                raise ValueError("Os turnos têm o mesmo identificador e configurações diferentes.")
            if existing is None:
                target.shifts.append(deepcopy(shift))
        copied = replace(deepcopy(group), id=str(uuid4()))
        target.groups.append(copied)
        if request.linked:
            link = source.shared_group_links.get(group.id, str(uuid4()))
            source.shared_group_links[group.id] = link
            target.shared_group_links[copied.id] = link
            if source.project_id == target.project_id:
                target.shared_group_links[group.id] = link
        target = EntityCodec.load(ProjectState, EntityCodec.dump(target))
        repository.save(
            target,
            related=[source] if request.linked and source.project_id != target.project_id else [],
        )
        return target
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail="Subdivisão ou grupo não encontrado.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.put("/api/project", response_model=ProjectSchema)
def save_project(project: ProjectSchema) -> ProjectState:
    try:
        return container.save_project.execute(EntityCodec.to_domain(project))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Não foi possível salvar o projeto: {exc}",
        ) from exc


@app.post("/api/project/reset", response_model=ProjectSchema)
def reset_project() -> ProjectState:
    try:
        return container.reset_project.execute()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Não foi possível criar um projeto vazio: {exc}",
        ) from exc


@app.post("/api/analyze")
def analyze(project: ProjectSchema) -> ProjectAnalysis:
    try:
        return container.analyze_project.execute(EntityCodec.to_domain(project))
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Falha ao analisar o projeto: {exc}",
        ) from exc


@app.post("/api/optimize")
def optimize_schedule(request: OptimizationRequest) -> OptimizationResult:
    """Calcula uma proposta; somente PUT /api/project pode aplicá-la."""
    try:
        return container.optimize_schedule.execute(
            EntityCodec.to_domain(request.project), EntityCodec.to_domain(request.options)
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"Falha na busca: {exc}") from exc


@app.get("/api/export.csv")
def export_csv() -> Response:
    """Exporta a cobertura prevista por data e turno, em CSV compatível com Excel."""
    try:
        project = container.load_project.execute()
        result = container.analyze_project.execute(project)
    except (RuntimeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "Data",
            "Dia da semana",
            "Turno",
            "Necessário",
            "Previsto na escala",
            "Déficit",
            "Sobra",
            "Horas-pessoa requeridas",
            "Horas-pessoa previstas",
            "Horas-pessoa faltantes",
        ]
    )

    weekday_names = [
        "segunda",
        "terça",
        "quarta",
        "quinta",
        "sexta",
        "sábado",
        "domingo",
    ]

    for day in result["coverage_by_day"]:
        for shift in day["shifts"]:
            writer.writerow(
                [
                    day["date"],
                    weekday_names[day["weekday"]],
                    shift["shift_name"],
                    shift["required"],
                    shift["scheduled"],
                    shift["deficit"],
                    shift["surplus"],
                    shift["required_work_hours"],
                    shift["scheduled_work_hours"],
                    shift["deficit_work_hours"],
                ]
            )

    csv_bytes = ("\ufeff" + output.getvalue()).encode("utf-8")

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": (f'attachment; filename="escala-{project.year}.csv"')},
    )
