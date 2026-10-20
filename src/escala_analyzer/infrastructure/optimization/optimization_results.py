"""Evaluation, deduplication and ranking of schedule proposals."""

from __future__ import annotations

from time import monotonic

from escala_analyzer.domain.analysis.project_analyzer import ProjectAnalyzer
from escala_analyzer.domain.contracts.optimization_contracts import (
    HoursOptimizationReport,
    OptimizationResult,
    OptimizationSolution,
    ProposalSignature,
    SearchStage,
)
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.domain.optimization.optimization_options import OptimizationOptions
from escala_analyzer.infrastructure.optimization.proposal_evaluator import ProposalEvaluator

ADDITIONS_SCOPE = (
    "Ciclos, equipes e ajustes dos grupos atuais permanecem intactos. Horas só mudam com autorização por grupo e na busca. As alternativas acrescentam equipes fixas por "
    "turno, que podem compartilhar ciclo e fase. Violações e faltas de cobertura são exibidas. "
    "A lista reúne as alternativas encontradas até o prazo ou limite configurado, "
    "ordenadas conforme as prioridades de aceitação do projeto; "
    "não garante o melhor resultado possível. Quando autorizado, cada combinação recebe um ajuste de sete jornadas por grupo; a busca não enumera todos os perfis de horas. A cobertura de horas é capacidade diária agregada, sem simular cobertura simultânea minuto a minuto ou posicionamento das pausas."
)


class OptimizationResults:
    """Own the accepted alternatives and their search report for one invocation."""

    def __init__(
        self,
        project: ProjectState,
        options: OptimizationOptions,
        started: float,
        analyzer: ProjectAnalyzer,
    ) -> None:
        self.project = project
        self.options = options
        self.started = started
        self.deadline = started + options.time_limit_seconds
        self.evaluator = ProposalEvaluator(project, options, analyzer)
        self.solutions: list[OptimizationSolution] = []
        self.signatures: set[ProposalSignature] = set()
        self.stages: list[SearchStage] = []
        self.limited = False
        self.exhausted = False
        self.warnings: list[str] = []
        settings = [project.rules, *(period.rules for period in project.rule_periods)]
        if any(not rule.check_intershift_rest for rule in settings):
            self.warnings.append(
                "A verificação de descanso entre jornadas está desligada em parte ou todo o período."
            )
        if any(not rule.check_breaks for rule in settings):
            self.warnings.append(
                "A verificação de intervalo intrajornada está desligada em parte ou todo o período."
            )
        if any(shift.start_time is None for shift in project.shifts):
            self.warnings.append(
                "Há turnos sem início: descanso entre jornadas pode não ser verificável."
            )

    def retain(
        self,
        proposal: ProjectState,
        baseline: bool = False,
        hour_report: HoursOptimizationReport | None = None,
    ) -> None:
        signature = tuple(
            (
                g.id,
                tuple(g.blocks),
                g.cycle_phase_offset,
                tuple(sorted(g.allocations.items())),
                tuple(g.work_hours_by_weekday),
            )
            for g in proposal.groups
        )
        if signature in self.signatures:
            return
        if len(self.solutions) >= self.options.max_solutions:
            self.limited = True
            return
        solution = self.evaluator.evaluate(
            proposal, baseline, hour_report, len(self.solutions), self.stages
        )
        if solution is None:
            return
        self.signatures.add(signature)
        self.solutions.append(solution)

        if len(self.solutions) >= self.options.max_solutions:
            self.limited = True

    def result(self) -> OptimizationResult:
        ordered = sorted(
            self.solutions,
            key=lambda solution: (not solution["business_acceptable"], solution["ranking"]),
        )
        best = ordered[0]
        partial = bool(
            best["metrics"]["rule_violation_count"]
            or best["metrics"]["deficit_staff_days"]
            or best["metrics"]["deficit_work_hours"]
        )
        status = "partial" if partial else "feasible"
        if len(ordered) == 1 and monotonic() >= self.deadline:
            status = "timeout"
        return {
            "status": status,
            "project": best["project"],
            "metrics": best["metrics"],
            "solutions": ordered,
            "optimal": False,
            "search_complete": self.exhausted and not self.options.optimize_work_hours,
            "solutions_found": len(ordered),
            "solution_limit": self.options.max_solutions,
            "truncated": self.limited,
            "stages": self.stages,
            "warnings": self.warnings,
            "priorities": self.project.optimization_priorities,
            "scope": (
                "Ajusta quantidades, ciclos e fases dos grupos existentes conforme as permissões. Preserva identidade, turnos, revezamento e ajustes por data. Busca limitada pelo prazo; não garante ótimo global. Horas-pessoa são capacidade diária agregada."
                if self.options.optimize_existing
                else ADDITIONS_SCOPE
            ),
            "rejected_patterns": [],
            "candidate_cycle_count": len(self.options.candidate_cycles()),
            "max_cycle_days": self.options.max_cycle_days
            if self.options.automatic_cycles
            else None,
            "elapsed_seconds": round(monotonic() - self.started, 3),
            "message": f"{len(ordered)} alternativa(s) encontrada(s). "
            + (
                "Limite de alternativas atingido."
                if self.limited
                else "Busca encerrada pelo prazo."
                if not self.exhausted
                else "Espaço de complementos esgotado."
            ),
        }
