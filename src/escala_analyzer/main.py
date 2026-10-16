"""Ponto de entrada da aplicação web local Escala Visual."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from escala_analyzer.domain.analyzer import analyze_project
from escala_analyzer.domain.models import ProjectState
from escala_analyzer.infrastructure.json_repository import JsonProjectRepository

WEB_DIR = Path(__file__).parent / "web"
repository = JsonProjectRepository()

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


@app.get("/api/project", response_model=ProjectState)
def get_project() -> ProjectState:
    try:
        return repository.load()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put("/api/project", response_model=ProjectState)
def save_project(project: ProjectState) -> ProjectState:
    try:
        repository.save(project)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=f"Não foi possível salvar o projeto: {exc}") from exc
    return project


@app.post("/api/project/reset", response_model=ProjectState)
def reset_project() -> ProjectState:
    try:
        return repository.reset()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Não foi possível restaurar o exemplo: {exc}") from exc


@app.post("/api/analyze")
def analyze(project: ProjectState) -> dict[str, Any]:
    try:
        return analyze_project(project)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"Falha ao analisar o projeto: {exc}") from exc


@app.get("/api/export.csv")
def export_csv() -> Response:
    """Exporta a cobertura prevista por data e turno, em CSV compatível com Excel."""
    try:
        project = repository.load()
        result = analyze_project(project)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        ["Data", "Dia da semana", "Turno", "Necessário", "Previsto na escala", "Déficit", "Sobra"]
    )
    weekday_names = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
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
                ]
            )

    csv_bytes = ("\ufeff" + output.getvalue()).encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="escala-{project.year}.csv"'},
    )