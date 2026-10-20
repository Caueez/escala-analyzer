"""Optimize weekly hour profiles while preserving groups and cycles."""

from __future__ import annotations

from copy import deepcopy
from time import monotonic

from ortools.sat.python import cp_model

from escala_analyzer.domain.contracts.optimization_contracts import (
    HoursOptimizationReport,
    SearchStage,
)
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.infrastructure.optimization.hour_model import HourModel, HourModelBuilder
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec


class GroupHoursOptimizer:
    def optimize(
        self, project: ProjectState, step: int, seconds: float
    ) -> tuple[ProjectState, HoursOptimizationReport]:
        deadline = monotonic() + seconds
        eligible = [
            g for g in project.groups if g.allow_hours_optimization and any(g.allocations.values())
        ]
        if not eligible or seconds <= 0:
            return project, {"status": "unchanged", "groups": []}
        built = HourModelBuilder().build(project, eligible, step, deadline)
        if not isinstance(built, HourModel):
            return project, built
        model, variables, base_groups = built.model, built.variables, built.base_groups
        solver, status = None, None
        stages: list[SearchStage] = []
        final_values = None
        hour_objectives = built.objectives
        by_priority = dict(
            zip(
                ("deficit_staff_days", "deficit_work_hours", "rule_violation_count"),
                hour_objectives[:3],
            )
        )
        ordered = [
            by_priority[key] for key in project.optimization_priorities if key in by_priority
        ]
        for name, objective in ordered + hour_objectives[3:]:
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            model.minimize(objective)
            solver = cp_model.CpSolver()
            solver.parameters.num_search_workers = 1
            solver.parameters.max_time_in_seconds = remaining
            status = solver.solve(model)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                break
            final_values = {key: solver.value(var) * step / 60 for key, var in variables.items()}
            value = solver.value(objective)
            stages.append(
                {"objective": name, "value": value, "optimal": status == cp_model.OPTIMAL}
            )
            if status != cp_model.OPTIMAL:
                break
            model.add(objective == value)
        if final_values is None:
            return project, {"status": "no_solution", "groups": [], "stages": stages}
        proposal = deepcopy(project)
        changed = []
        for group in proposal.groups:
            if group.id in base_groups:
                previous = list(group.work_hours_by_weekday)
                group.work_hours_by_weekday = [final_values[group.id, day] for day in range(7)]
                if previous != group.work_hours_by_weekday:
                    changed.append(group.id)
        return EntityCodec.load(ProjectState, EntityCodec.dump(proposal)), {
            "status": "optimized",
            "groups": changed,
            "stages": stages,
            "scope": "Sete jornadas efetivas por grupo. Cobertura em pessoas e horas-pessoa; não simula cobertura minuto a minuto ou a posição das pausas.",
        }
