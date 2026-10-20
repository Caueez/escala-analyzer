"""Construct the discrete weekday hour model and coverage objectives."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil, floor
from time import monotonic

from ortools.sat.python import cp_model

from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.contracts.optimization_contracts import HoursOptimizationReport
from escala_analyzer.domain.entities import ProjectState, ScheduleGroup
from escala_analyzer.infrastructure.optimization.hour_expressions import HourExpressions, HourKey
from escala_analyzer.infrastructure.optimization.hour_rule_constraints import HourRuleConstraints


@dataclass(frozen=True)
class HourModel:
    model: cp_model.CpModel
    variables: dict[HourKey, cp_model.IntVar]
    base_groups: dict[str, ScheduleGroup]
    objectives: list[tuple[str, cp_model.LinearExpr | int]]


class HourModelBuilder:
    def build(
        self, project: ProjectState, eligible: list[ScheduleGroup], step: int, deadline: float
    ) -> HourModel | HoursOptimizationReport:
        model = cp_model.CpModel()
        shifts = {s.id: s for s in project.shifts}
        dates = ScheduleCalendar.year_dates(project.year)
        variables: dict[HourKey, cp_model.IntVar] = {}
        presence: dict[HourKey, cp_model.IntVar] = {}
        base_groups: dict[str, ScheduleGroup] = {}
        deviations: list[cp_model.IntVar] = []
        for group in eligible:
            base_groups[group.id] = replace(group, work_hours_by_weekday=[None] * 7)
            max_elapsed = min(
                1440 - shifts[sid].break_minutes
                for sid, count in group.allocations.items()
                if count > 0
            )
            for weekday in range(7):
                low = ceil(group.min_hours_by_weekday[weekday] * 60 / step - 1e-9)
                high = min(
                    floor(group.max_hours_by_weekday[weekday] * 60 / step + 1e-9),
                    max_elapsed // step,
                )
                if low > high:
                    return {
                        "status": "invalid_bounds",
                        "groups": [group.id],
                        "message": f"{group.name}: os limites de {weekday + 1} não comportam a pausa e o passo de minutos.",
                    }
                units = model.new_int_var(low, high, f"hours_{group.id}_{weekday}")
                on = model.new_bool_var(f"on_{group.id}_{weekday}")
                model.add(units >= 1).only_enforce_if(on)
                model.add(units == 0).only_enforce_if(on.Not())
                variables[group.id, weekday] = units
                presence[group.id, weekday] = on
                configured = group.work_hours_by_weekday[weekday]
                target = round(
                    (
                        configured
                        if configured is not None
                        else max(
                            shifts[sid].work_hours
                            for sid, count in group.allocations.items()
                            if count > 0
                        )
                    )
                    * 60
                )
                deviation = model.new_int_var(0, 1440, f"change_{group.id}_{weekday}")
                model.add_abs_equality(deviation, units * step - target)
                deviations.append(deviation)

        expressions = HourExpressions(model, variables, presence, base_groups, shifts, step)
        deficits: list[cp_model.IntVar] = []
        missing_minutes: list[cp_model.IntVar] = []
        for shift in project.shifts:
            for day in dates:
                if monotonic() >= deadline:
                    return {"status": "timeout", "groups": []}
                teams = [
                    g
                    for g in project.groups
                    if g.staff_for(shift.id) > 0
                    and (not g.rotation_shift_ids or ScheduleCalendar.shift_on(g, day) == shift.id)
                ]
                supplied = sum(g.staff_for(shift.id) * expressions.active(g, day) for g in teams)
                supplied_minutes = sum(
                    g.staff_for(shift.id) * expressions.minutes(g, day, shift.id) for g in teams
                )
                required = shift.demand_by_date.get(
                    day.isoformat(), shift.demand_by_weekday[day.weekday()]
                )
                deficit = model.new_int_var(0, required, f"staff_{shift.id}_{day}")
                gap = model.new_int_var(
                    0, required * round(shift.work_hours * 60), f"minutes_{shift.id}_{day}"
                )
                model.add_max_equality(deficit, [required - supplied, 0])
                model.add_max_equality(
                    gap, [required * round(shift.work_hours * 60) - supplied_minutes, 0]
                )
                deficits.append(deficit)
                missing_minutes.append(gap)

        if not HourRuleConstraints().apply(project, eligible, expressions, deadline):
            return {"status": "timeout", "groups": []}
        return HourModel(
            model,
            variables,
            base_groups,
            [
                ("people_deficit", sum(deficits)),
                ("work_minutes_deficit", sum(missing_minutes)),
                ("rule_penalty", sum(expressions.penalties)),
                ("hour_changes", sum(deviations)),
            ],
        )
