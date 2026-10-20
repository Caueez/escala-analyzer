"""Restrições de operação, variedade de padrões e estimativa de custo mensal."""

from __future__ import annotations

from collections.abc import Sequence

from escala_analyzer.domain.contracts.analysis_contracts import AnalysisIssue
from escala_analyzer.domain.contracts.optimization_contracts import BusinessMetrics
from escala_analyzer.domain.entities import BusinessConstraints, ProjectState


class CyclePattern:
    @staticmethod
    def pattern_key(blocks: Sequence[int]) -> tuple[int, ...]:
        blocks = list(blocks)
        if len(blocks) == 1:
            return (1,)
        if len(blocks) % 2:
            blocks = [blocks[0] + blocks[-1], *blocks[1:-1]]
        for size in range(2, len(blocks) + 1, 2):
            if len(blocks) % size == 0 and blocks == blocks[:size] * (len(blocks) // size):
                blocks = blocks[:size]
                break
        return min(tuple(blocks[i:] + blocks[:i]) for i in range(0, len(blocks), 2))


class BusinessPolicy:
    @staticmethod
    def allowed_cycle(blocks: Sequence[int], policy: BusinessConstraints) -> bool:
        work = sum(blocks[::2])
        if work * 100 + 1e-8 < policy.min_work_percent * sum(blocks):
            return False
        return (
            policy.max_consecutive_rest_days is None
            or max(blocks[1::2], default=0) <= policy.max_consecutive_rest_days
        )

    @staticmethod
    def business_metrics(
        project: ProjectState, people: int
    ) -> tuple[BusinessMetrics, list[AnalysisIssue]]:
        policy = project.business_constraints
        active = [g for g in project.groups if any(g.allocations.values())]
        patterns = len({CyclePattern.pattern_key(g.blocks) for g in active})
        cost = round(people * policy.monthly_employee_cost, 2)
        issues: list[AnalysisIssue] = []

        def issue(code: str, message: str) -> None:
            issues.append(
                {
                    "code": code,
                    "severity": "rule",
                    "title": "Limite operacional da empresa",
                    "message": message,
                }
            )

        if policy.max_schedule_patterns is not None and patterns > policy.max_schedule_patterns:
            issue(
                "schedule-pattern-limit",
                f"{patterns} tipos de escala; máximo {policy.max_schedule_patterns}.",
            )
        if policy.monthly_budget is not None and cost > policy.monthly_budget + 0.001:
            issue(
                "monthly-budget",
                f"Custo mensal estimado R$ {cost:.2f}; orçamento R$ {policy.monthly_budget:.2f}.",
            )
        for group in active:
            if not BusinessPolicy.allowed_cycle(group.blocks, policy):
                issue(
                    "impractical-cycle",
                    f"{group.name}: ciclo fora dos limites de proporção de trabalho ou folgas consecutivas.",
                )
        return {"pattern_count": patterns, "monthly_staff_cost": cost}, issues


# Compatibility adapters for existing public imports.
def pattern_key(blocks: Sequence[int]) -> tuple[int, ...]:
    return CyclePattern.pattern_key(blocks)


def allowed_cycle(blocks: Sequence[int], policy: BusinessConstraints) -> bool:
    return BusinessPolicy.allowed_cycle(blocks, policy)


def business_metrics(
    project: ProjectState, people: int
) -> tuple[BusinessMetrics, list[AnalysisIssue]]:
    return BusinessPolicy.business_metrics(project, people)
