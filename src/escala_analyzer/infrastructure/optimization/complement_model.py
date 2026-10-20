"""Build staffing constraints and objectives for additional teams."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from ortools.sat.python import cp_model

from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.contracts.optimization_contracts import CandidatePattern, PatternKey
from escala_analyzer.domain.entities import ProjectState
from escala_analyzer.domain.optimization.optimization_options import OptimizationOptions

from .business_model_constraints import BusinessModelConstraints


@dataclass(frozen=True)
class ComplementModel:
    model: cp_model.CpModel
    sizes: list[cp_model.IntVar]
    by_pattern: dict[PatternKey, list[int]]
    variables: list[cp_model.IntVar]
    objectives: list[tuple[str, cp_model.LinearExpr | int]]


class ComplementModelBuilder:
    def build(
        self,
        project: ProjectState,
        search_project: ProjectState,
        options: OptimizationOptions,
        patterns: list[CandidatePattern],
        free_groups: int,
        free_people: int,
        baseline_people: int,
        deadline: float,
        warnings: list[str],
    ) -> ComplementModel | None:
        dates = ScheduleCalendar.year_dates(project.year)
        model = cp_model.CpModel()
        sizes: list[cp_model.IntVar] = []
        active: list[cp_model.IntVar] = []
        counts: dict[PatternKey, cp_model.IntVar] = {}
        by_pattern: dict[PatternKey, list[int]] = {}
        for i, pattern in enumerate(patterns):
            group = pattern.group
            key = (tuple(group.blocks), group.cycle_phase_offset)
            if key not in counts:
                counts[key] = model.new_int_var(0, free_groups, f"groups_{len(counts)}")
                by_pattern[key] = []
            size = model.new_int_var(0, free_people, f"people_{i}")
            enabled = model.new_bool_var(f"active_{i}")
            model.add(size <= options.max_group_size * counts[key])
            model.add(size <= free_people * enabled)
            model.add(size >= enabled)
            by_pattern[key].append(i)
            sizes.append(size)
            active.append(enabled)
        if not options.allow_mixed_cycles_per_shift:
            for shift in project.shifts:
                fixed = {tuple(g.blocks) for g in project.groups if g.staff_for(shift.id) > 0}
                if len(fixed) > 1:
                    warnings.append(f"{shift.name}: os grupos preservados já misturam ciclos.")
                selectors: dict[tuple[int, ...], cp_model.IntVar] = {}
                for i, pattern in enumerate(patterns):
                    group = pattern.group
                    if group.shift_id != shift.id:
                        continue
                    cycle = tuple(group.blocks)
                    if fixed and cycle not in fixed:
                        model.add(active[i] == 0)
                    if cycle not in selectors:
                        selectors[cycle] = model.new_bool_var(f"cycle_{shift.id}_{len(selectors)}")
                    model.add(active[i] <= selectors[cycle])
                model.add(sum(selectors.values()) <= 1)
        for key, count in counts.items():
            model.add(count <= sum(sizes[i] for i in by_pattern[key]))
        model.add(sum(counts.values()) <= free_groups)
        model.add(sum(sizes) <= free_people)
        deficits: list[cp_model.IntVar] = []
        surpluses: list[cp_model.IntVar] = []
        hour_deficits: list[cp_model.IntVar] = []
        for shift in project.shifts:
            for di, day in enumerate(dates):
                if monotonic() >= deadline:
                    return
                required = shift.demand_by_date.get(
                    day.isoformat(), shift.demand_by_weekday[day.weekday()]
                )
                existing = sum(
                    g.staff_for(shift.id)
                    for g in search_project.groups
                    if ScheduleCalendar.works_shift(g, shift.id, day)
                )
                staffing = existing + sum(
                    sizes[i]
                    for i, pattern in enumerate(patterns)
                    if pattern.group.shift_id == shift.id and pattern.working_days[di]
                )
                deficit = model.new_int_var(0, required, f"deficit_{shift.id}_{di}")
                surplus = model.new_int_var(0, existing + free_people, f"surplus_{shift.id}_{di}")
                model.add_max_equality(deficit, [required - staffing, 0])
                model.add_max_equality(surplus, [staffing - required, 0])
                required_minutes = required * round(shift.work_hours * 60)
                provided_minutes = sum(
                    g.staff_for(shift.id) * round(ScheduleCalendar.work_hours(g, shift, day) * 60)
                    for g in search_project.groups
                    if ScheduleCalendar.works_shift(g, shift.id, day)
                ) + sum(
                    sizes[i] * round(ScheduleCalendar.work_hours(pattern.group, shift, day) * 60)
                    for i, pattern in enumerate(patterns)
                    if pattern.group.shift_id == shift.id and pattern.working_days[di]
                )
                hour_deficit = model.new_int_var(
                    0, required_minutes, f"hour_deficit_{shift.id}_{di}"
                )
                model.add_max_equality(hour_deficit, [required_minutes - provided_minutes, 0])
                hour_deficits.append(hour_deficit)
                deficits.append(deficit)
                surpluses.append(surplus)
        pattern_objective = BusinessModelConstraints.constrain_patterns(
            model,
            project,
            [(pattern.group.blocks, active[i], 1) for i, pattern in enumerate(patterns)],
            fixed=project.groups,
        )
        cost_objective = BusinessModelConstraints.constrain_budget(
            model, project, sum(sizes) + baseline_people
        )
        count_vars = list(counts.values())
        variables = sizes + count_vars
        objectives: list[tuple[str, cp_model.LinearExpr | int]] = [
            ("deficit_staff_days", sum(deficits)),
            ("deficit_work_minutes", sum(hour_deficits)),
            (
                "rule_penalty",
                sum(active[i] * pattern.rule_issue_count for i, pattern in enumerate(patterns)),
            ),
            ("groups", sum(count_vars)),
            ("surplus_staff_days", sum(surpluses)),
            ("people", sum(sizes)),
        ]

        objective_map: dict[str, tuple[str, cp_model.LinearExpr | int]] = dict(
            zip(
                (
                    "deficit_staff_days",
                    "deficit_work_hours",
                    "rule_violation_count",
                    "group_count",
                    "surplus_staff_days",
                    "people_total",
                ),
                objectives,
            )
        )
        objective_map["pattern_count"] = ("pattern_count", pattern_objective)
        objective_map["monthly_staff_cost"] = ("monthly_staff_cost", cost_objective)
        objectives = [objective_map[key] for key in project.optimization_priorities]

        return ComplementModel(model, sizes, by_pattern, variables, objectives)
