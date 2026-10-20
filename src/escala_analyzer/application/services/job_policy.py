"""Bound expensive requests before accepting durable work."""

from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.domain.optimization.optimization_options import OptimizationOptions


class JobPolicy:
    @staticmethod
    def validate(project: ProjectState, options: OptimizationOptions | None = None) -> None:
        if len(project.groups) > 200 or len(project.shifts) > 20 or len(project.rule_periods) > 24:
            raise ValueError("Limites por trabalho: 200 grupos, 20 turnos e 24 vigências.")
        if any(len(group.blocks) > 200 or group.cycle_length > 10000 for group in project.groups):
            raise ValueError("Ciclos do trabalho excedem os limites de processamento.")
        if (
            sum(
                1 if group.rotation_shift_ids else len(group.allocations)
                for group in project.groups
            )
            > 200
        ):
            raise ValueError("Limite de 200 equipes alocadas por trabalho excedido.")
        if (
            options
            and sum(sum(cycle.blocks) for cycle in options.candidate_cycles())
            * max(1, len(project.shifts))
            > 10000
        ):
            raise ValueError("Busca acima de 10.000 padrões/fases. Reduza ciclos ou turnos.")
