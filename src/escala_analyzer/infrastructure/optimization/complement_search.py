"""Search additional fixed teams with CP-SAT."""

from __future__ import annotations

from time import monotonic

from ortools.sat.python import cp_model

from escala_analyzer.domain.contracts.optimization_contracts import SearchStage
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.domain.optimization.candidate_patterns import CandidatePatternFactory
from escala_analyzer.domain.optimization.optimization_options import OptimizationOptions
from escala_analyzer.infrastructure.optimization.complement_model import ComplementModelBuilder
from escala_analyzer.infrastructure.optimization.complement_proposal import (
    ComplementProposalBuilder,
)
from escala_analyzer.infrastructure.optimization.hours_adjustment import HoursAdjustment
from escala_analyzer.infrastructure.optimization.optimization_results import OptimizationResults


class ComplementSearch:
    def search(
        self,
        project: ProjectState,
        search_project: ProjectState,
        options: OptimizationOptions,
        results: OptimizationResults,
        hours: HoursAdjustment,
    ) -> None:
        vectors: set[tuple[int, ...]] = set()
        free_groups = max(0, options.max_groups - len(project.groups))
        free_people = max(
            0, options.max_employees - results.solutions[0]["metrics"]["people_total"]
        )
        if free_groups == 0 or free_people == 0 or not project.shifts:
            results.exhausted = True
            return
        patterns = CandidatePatternFactory().create(project, options, results.deadline)
        if patterns is None:
            return
        if not patterns:
            results.warnings.append(
                "Nenhum ciclo candidato atende aos limites de proporção de trabalho e folgas da empresa. Revise os candidatos ou os limites operacionais."
            )
            results.exhausted = True
            return
        built = ComplementModelBuilder().build(
            project,
            search_project,
            options,
            patterns,
            free_groups,
            free_people,
            results.solutions[0]["metrics"]["people_total"],
            results.deadline,
            results.warnings,
        )
        if built is None:
            return
        model, sizes = built.model, built.sizes
        by_pattern, variables, objectives = built.by_pattern, built.variables, built.objectives

        builder = ComplementProposalBuilder(
            project, search_project, patterns, by_pattern, len(sizes)
        )
        while not results.limited and monotonic() < results.deadline:
            trial = model.clone()
            found_vector = None
            for name, objective in objectives:
                remaining = results.deadline - monotonic()
                if remaining <= 0 or results.limited:
                    break
                trial.minimize(objective)
                solver = cp_model.CpSolver()
                solver.parameters.max_time_in_seconds = remaining
                solver.parameters.num_search_workers = 1
                status = solver.solve(trial)
                stage: SearchStage = {
                    "objective": name,
                    "status": solver.status_name(status).lower(),
                    "seconds": solver.wall_time,
                }
                results.stages.append(stage)
                if status == cp_model.INFEASIBLE:
                    results.exhausted = True
                    break
                if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    break
                found_vector = tuple(solver.value(var) for var in variables)
                if status != cp_model.OPTIMAL:
                    break
                trial.add(objective == int(solver.value(objective)))
            if found_vector is not None and found_vector not in vectors:
                vectors.add(found_vector)
                adjusted, report = hours.fit(builder.build(found_vector))
                results.retain(adjusted, hour_report=report)
            if results.exhausted or results.limited or monotonic() >= results.deadline:
                break
            if found_vector is None:
                break
            model.add_forbidden_assignments(variables, list(vectors))
