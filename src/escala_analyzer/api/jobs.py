"""Asynchronous analysis/search/export, with tenant-scoped status and results."""

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from escala_analyzer.api.dependencies import Access
from escala_analyzer.application.services.identity import Principal
from escala_analyzer.application.services.job_policy import JobPolicy
from escala_analyzer.infrastructure.database.models import Job
from escala_analyzer.infrastructure.schemas.optimization import OptimizationRequest
from escala_analyzer.infrastructure.schemas.project import ProjectState as ProjectSchema
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec

router = APIRouter(prefix="/api", tags=["jobs"])


class JobViewBuilder:
    @staticmethod
    def view(job: Job) -> dict:
        return {
            "id": job.id,
            "kind": job.kind,
            "state": job.state,
            "rules_version": job.rules_version,
            "error_code": job.error_code,
            "created_at": job.created_at.isoformat(),
            "status_url": f"/api/jobs/{job.id}",
            "result_url": f"/api/jobs/{job.id}/result",
        }

    @staticmethod
    def key(value: str | None) -> str:
        if not value or not 8 <= len(value) <= 128:
            raise HTTPException(400, "Informe Idempotency-Key com 8 a 128 caracteres.")
        return value


@router.post("/analyze", status_code=202)
def analyze(
    payload: ProjectSchema,
    request: Request,
    principal: Annotated[Principal, Depends(Access.current)],
    idempotency_key: str | None = Header(default=None),
) -> dict:
    JobPolicy.validate(EntityCodec.to_domain(payload))
    job = request.app.state.jobs.enqueue(
        principal,
        "analysis",
        {"project": payload.model_dump(mode="json")},
        JobViewBuilder.key(idempotency_key),
    )
    return JobViewBuilder.view(job)


@router.post("/optimize", status_code=202)
def optimize(
    payload: OptimizationRequest,
    request: Request,
    principal: Annotated[Principal, Depends(Access.editor)],
    idempotency_key: str | None = Header(default=None),
) -> dict:
    JobPolicy.validate(
        EntityCodec.to_domain(payload.project), EntityCodec.to_domain(payload.options)
    )
    # Preserve the explicit/manual-cycle semantics when reconstructing in a worker.
    options = payload.options.model_dump(mode="json")
    options["automatic_cycles"] = EntityCodec.to_domain(payload.options).automatic_cycles
    job = request.app.state.jobs.enqueue(
        principal,
        "optimization",
        {"project": payload.project.model_dump(mode="json"), "options": options},
        JobViewBuilder.key(idempotency_key),
    )
    return JobViewBuilder.view(job)


@router.post("/export", status_code=202)
def export(
    payload: ProjectSchema,
    request: Request,
    principal: Annotated[Principal, Depends(Access.current)],
    idempotency_key: str | None = Header(default=None),
) -> dict:
    JobPolicy.validate(EntityCodec.to_domain(payload))
    return JobViewBuilder.view(
        request.app.state.jobs.enqueue(
            principal,
            "export",
            {"project": payload.model_dump(mode="json")},
            JobViewBuilder.key(idempotency_key),
        )
    )


@router.get("/jobs/{job_id}")
def status(
    job_id: str, request: Request, principal: Annotated[Principal, Depends(Access.current)]
) -> dict:
    return JobViewBuilder.view(request.app.state.jobs.get(principal, job_id))


@router.get("/jobs/{job_id}/result")
def result(
    job_id: str, request: Request, principal: Annotated[Principal, Depends(Access.current)]
) -> dict:
    job = request.app.state.jobs.get(principal, job_id)
    if job.state != "succeeded" or job.result is None:
        raise HTTPException(409, "O resultado ainda não está disponível.")
    if job.kind == "export":
        return {"download_url": f"/api/jobs/{job_id}/download"}
    return job.result


@router.get("/jobs/{job_id}/download")
def download(
    job_id: str, request: Request, principal: Annotated[Principal, Depends(Access.current)]
) -> Response:
    job = request.app.state.jobs.get(principal, job_id)
    if job.state != "succeeded" or job.kind != "export" or job.result is None:
        raise HTTPException(404, "Exportação indisponível.")
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(
        [
            "Data",
            "Turno",
            "Demanda",
            "Escalados",
            "Déficit",
            "Excedente",
            "Horas requeridas",
            "Horas escaladas",
            "Déficit de horas",
        ]
    )
    for day in job.result["coverage_by_day"]:
        for shift in day["shifts"]:
            name = shift["shift_name"]
            if name.lstrip().startswith(("=", "+", "-", "@")):
                name = "'" + name
            writer.writerow(
                [
                    day["date"],
                    name,
                    shift["required"],
                    shift["scheduled"],
                    shift["deficit"],
                    shift["surplus"],
                    shift["required_work_hours"],
                    shift["scheduled_work_hours"],
                    shift["deficit_work_hours"],
                ]
            )
    return Response(
        "\ufeff" + stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="cobertura.csv"'},
    )


@router.post("/jobs/{job_id}/cancel")
def cancel(
    job_id: str, request: Request, principal: Annotated[Principal, Depends(Access.current)]
) -> dict:
    return JobViewBuilder.view(request.app.state.jobs.cancel(principal, job_id))
