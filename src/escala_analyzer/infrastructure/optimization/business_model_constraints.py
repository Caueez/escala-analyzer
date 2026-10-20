"""OR-Tools translation of the domain business policy."""

from __future__ import annotations

from collections.abc import Sequence

from ortools.sat.python import cp_model

from escala_analyzer.domain.entities import ProjectState, ScheduleGroup
from escala_analyzer.domain.policies.business_constraints import BusinessPolicy, CyclePattern


class BusinessModelConstraints:
    @staticmethod
    def constrain_patterns(
        model: cp_model.CpModel,
        project: ProjectState,
        entries: Sequence[tuple[Sequence[int], cp_model.IntVar, int]],
        fixed: Sequence[ScheduleGroup] = (),
    ) -> cp_model.LinearExpr | int:
        """entries: (blocos, variável booleana ou quantidade, limite superior)."""
        selectors: dict[tuple[int, ...], cp_model.IntVar] = {}
        fixed_keys = {
            CyclePattern.pattern_key(g.blocks) for g in fixed if any(g.allocations.values())
        }
        for blocks, var, maximum in entries:
            key = CyclePattern.pattern_key(blocks)
            if key not in selectors:
                selectors[key] = model.new_bool_var(f"business_pattern_{len(selectors)}")
            model.add(var <= maximum * selectors[key])
            if not BusinessPolicy.allowed_cycle(blocks, project.business_constraints):
                model.add(var == 0)
        for key in fixed_keys:
            if key not in selectors:
                selectors[key] = model.new_bool_var(f"business_pattern_{len(selectors)}")
            model.add(selectors[key] == 1)
        limit = project.business_constraints.max_schedule_patterns
        if limit is not None:
            model.add(sum(selectors.values()) <= limit)
        # Link selectors in both directions, so enumeration cannot invent unused patterns.
        for key, selected in selectors.items():
            if key not in fixed_keys:
                model.add(
                    selected
                    <= sum(
                        var for blocks, var, _ in entries if CyclePattern.pattern_key(blocks) == key
                    )
                )
        return sum(selectors.values())

    @staticmethod
    def constrain_budget(
        model: cp_model.CpModel,
        project: ProjectState,
        people: cp_model.LinearExpr | int,
    ) -> cp_model.LinearExpr | int:
        from decimal import ROUND_FLOOR, Decimal

        policy = project.business_constraints
        if policy.monthly_budget is not None:
            cap = int(
                (
                    Decimal(str(policy.monthly_budget)) / Decimal(str(policy.monthly_employee_cost))
                ).to_integral_value(rounding=ROUND_FLOOR)
            )
            model.add(people <= cap)
        # Whole cents avoid floating point objectives in CP-SAT.
        return people * round(policy.monthly_employee_cost * 100)
