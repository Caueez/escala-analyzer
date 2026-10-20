"""Busca conjunta de padrões e tamanhos sem substituir a identidade dos grupos."""

from __future__ import annotations

from copy import deepcopy
from time import monotonic
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from escala_analyzer.domain.contracts.optimization_contracts import SearchStage
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.infrastructure.optimization.existing_groups_model import (
    ExistingGroupsModelBuilder,
)
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec

if TYPE_CHECKING:
    from escala_analyzer.domain.optimization.optimization_options import OptimizationOptions


class ExistingGroupsOptimizer:
    """Search permitted changes to the patterns and sizes of existing groups."""

    def optimize(
        self, project: ProjectState, options: OptimizationOptions, deadline: float
    ) -> tuple[list[ProjectState], list[SearchStage]]:
        built = ExistingGroupsModelBuilder().build(project, options, deadline)
        if built is None:
            return [], []
        model, patterns, variables, objectives = (
            built.model,
            built.patterns,
            built.variables,
            built.objectives,
        )
        proposals: list[ProjectState] = []
        stages: list[SearchStage] = []
        while monotonic() < deadline and len(proposals) < options.max_solutions - 1:
            trial = model.clone()
            values = None
            for key in project.optimization_priorities:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                objective = objectives[key]
                trial.minimize(objective)
                solver = cp_model.CpSolver()
                solver.parameters.max_time_in_seconds = remaining
                solver.parameters.num_search_workers = 1
                status = solver.solve(trial)
                stages.append({"objective": key, "status": solver.status_name(status).lower()})
                if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    break
                values = [solver.value(v) for v in variables]
                if status != cp_model.OPTIMAL:
                    break
                trial.add(objective == solver.value(objective))
            if values is None:
                break
            by_index = {v.index: value for v, value in zip(variables, values)}
            proposal = deepcopy(project)
            updated = {}
            for pattern in patterns:
                if by_index[pattern.selected.index]:
                    group = deepcopy(pattern.group)
                    group.allocations = {
                        sid: by_index[size.index] for sid, size in pattern.allocations.items()
                    }
                    group.employee_count = (
                        next(iter(group.allocations.values()), 0)
                        if group.rotation_shift_ids
                        else sum(group.allocations.values())
                    )
                    updated[pattern.group_id] = group
            proposal.groups = [updated[g.id] for g in project.groups]
            proposals.append(EntityCodec.load(ProjectState, EntityCodec.dump(proposal)))
            model.add_forbidden_assignments(variables, [values])
        return proposals, stages


def optimize_existing_groups(
    project: ProjectState, options: OptimizationOptions, deadline: float
) -> tuple[list[ProjectState], list[SearchStage]]:
    """Compatibility entry point for existing callers."""
    return ExistingGroupsOptimizer().optimize(project, options, deadline)
