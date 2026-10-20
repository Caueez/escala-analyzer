"""Evaluate a proposal against analysis results and configured limits."""

from __future__ import annotations

from escala_analyzer.domain.analysis.project_analyzer import ProjectAnalyzer
from escala_analyzer.domain.contracts.analysis_contracts import AnalysisIssue
from escala_analyzer.domain.contracts.optimization_contracts import (
    HoursOptimizationReport,
    OptimizationMetrics,
    OptimizationSolution,
    SearchStage,
)
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.domain.optimization.optimization_options import OptimizationOptions
from escala_analyzer.domain.policies.business_constraints import BusinessPolicy
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec


class ProposalEvaluator:
    def __init__(
        self, project: ProjectState, options: OptimizationOptions, analyzer: ProjectAnalyzer
    ) -> None:
        self.project = project
        self.options = options
        self.analyzer = analyzer

    def evaluate(
        self,
        proposal: ProjectState,
        baseline: bool,
        hour_report: HoursOptimizationReport | None,
        ordinal: int,
        stages: list[SearchStage],
    ) -> OptimizationSolution | None:
        additions = proposal.groups[len(self.project.groups) :]
        analysis = self.analyzer.analyze(proposal, include_details=False)
        limits: list[AnalysisIssue] = []
        if hour_report and hour_report.get("status") not in {"optimized", "unchanged"}:
            limits.append(
                {
                    "code": "hours-optimization",
                    "severity": "rule",
                    "title": "Ajuste de horas não concluído",
                    "message": hour_report.get(
                        "message",
                        "Não foi encontrada uma jornada ajustada no prazo e limites configurados.",
                    ),
                }
            )
        if len(proposal.groups) > self.options.max_groups:
            limits.append(
                {
                    "code": "group-limit",
                    "severity": "rule",
                    "title": "Limite de grupos excedido",
                    "message": "Grupos existentes preservados apesar do limite.",
                    "actual": len(proposal.groups),
                    "expected": self.options.max_groups,
                }
            )
        if analysis["people_total"] > self.options.max_employees:
            limits.append(
                {
                    "code": "people-limit",
                    "severity": "rule",
                    "title": "Limite de pessoas excedido",
                    "message": "Pessoas existentes preservadas apesar do limite.",
                    "actual": analysis["people_total"],
                    "expected": self.options.max_employees,
                }
            )
        for group in proposal.groups:
            if any(count > self.options.max_group_size for count in group.allocations.values()):
                limits.append(
                    {
                        "code": "group-size-limit",
                        "severity": "rule",
                        "group_id": group.id,
                        "title": "Tamanho da equipe excedido",
                        "message": group.name,
                        "actual": max(group.allocations.values()),
                        "expected": self.options.max_group_size,
                    }
                )
        business, business_issues = BusinessPolicy.business_metrics(
            proposal, analysis["people_total"]
        )
        if business_issues and not baseline:
            return
        limits.extend(business_issues)
        metrics: OptimizationMetrics = {
            **business,
            "rule_violation_count": analysis["rule_issue_count"] + len(limits),
            "limit_violation_count": len(limits),
            "group_count": len(proposal.groups),
            "people_total": analysis["people_total"],
            "deficit_staff_days": sum(
                item["deficit"] for day in analysis["coverage_by_day"] for item in day["shifts"]
            ),
            "surplus_staff_days": sum(
                item["surplus"] for day in analysis["coverage_by_day"] for item in day["shifts"]
            ),
            "added_group_count": len(additions),
            "deficit_work_hours": round(
                sum(
                    item["deficit_work_hours"]
                    for day in analysis["coverage_by_day"]
                    for item in day["shifts"]
                ),
                4,
            ),
        }
        rank = [metrics[key] for key in self.project.optimization_priorities]
        return {
            "id": "baseline" if baseline else f"solution-{ordinal}",
            "baseline": baseline,
            "business_acceptable": not business_issues,
            "hours_optimization": hour_report,
            "group_changes": [
                {
                    "group_id": old.id,
                    "group_name": old.name,
                    "before": EntityCodec.dump(old, mode="json"),
                    "after": EntityCodec.dump(new, mode="json"),
                }
                for old, new in zip(self.project.groups, proposal.groups)
                if old != new
            ],
            "hour_changes": [
                {
                    "group_id": original.id,
                    "group_name": original.name,
                    "before": original.work_hours_by_weekday,
                    "after": updated.work_hours_by_weekday,
                }
                for original, updated in zip(self.project.groups, proposal.groups)
                if original.work_hours_by_weekday != updated.work_hours_by_weekday
            ],
            "label": "Escala atual preservada"
            if baseline
            else "Jornadas ajustadas"
            if hour_report and hour_report.get("groups") and not additions
            else f"Projeto ajustado {ordinal}"
            if self.options.optimize_existing
            else f"Complemento {ordinal}",
            "project": EntityCodec.dump(proposal, mode="json"),
            "metrics": metrics,
            "issues": analysis["issues"] + limits,
            "ranking": rank,
            "optimal": False,
            "stages": list(stages),
        }
