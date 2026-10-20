"""Build the joint staffing model for existing schedule groups."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import monotonic

from ortools.sat.python import cp_model

from escala_analyzer.domain.analysis.schedule_rules_analyzer import ScheduleRulesAnalyzer
from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.entities import ProjectState, ScheduleGroup
from escala_analyzer.domain.optimization.existing_group_candidates import (
    ExistingGroupCandidateFactory,
)
from escala_analyzer.domain.optimization.optimization_options import OptimizationOptions

from .business_model_constraints import BusinessModelConstraints


@dataclass(frozen=True, slots=True)
class ExistingPattern:
    group_id: str
    group: ScheduleGroup
    selected: cp_model.IntVar
    allocations: dict[str, cp_model.IntVar]
    working_days_by_shift: dict[str, list[bool]]


@dataclass(frozen=True)
class ExistingGroupsModel:
    model: cp_model.CpModel
    patterns: list[ExistingPattern]
    variables: list[cp_model.IntVar]
    objectives: dict[str, cp_model.LinearExpr | int]


class ExistingGroupsModelBuilder:
    def build(
        self, project: ProjectState, options: OptimizationOptions, deadline: float
    ) -> ExistingGroupsModel | None:
        model = cp_model.CpModel()
        dates = ScheduleCalendar.year_dates(project.year)
        shifts = {s.id: s for s in project.shifts}
        patterns: list[ExistingPattern] = []
        variables: list[cp_model.IntVar] = []
        penalties: list[cp_model.LinearExpr] = []
        people: list[cp_model.IntVar] = []
        analyzer = ScheduleRulesAnalyzer()
        preparation_deadline = monotonic() + max(0, deadline - monotonic()) * 0.55
        for group_index, original in enumerate(project.groups):
            candidate_deadline = monotonic() + max(0, preparation_deadline - monotonic()) / (
                len(project.groups) - group_index
            )

            choices: list[cp_model.IntVar] = []
            for candidate in ExistingGroupCandidateFactory().create(
                original, options, candidate_deadline
            ):
                if monotonic() >= deadline:
                    return None
                choice = model.new_bool_var(f"choice_{len(patterns)}")
                choices.append(choice)
                variables.append(choice)
                allocations: dict[str, cp_model.IntVar] = {}
                shared = None
                for sid, count in original.allocations.items():
                    if original.rotation_shift_ids and shared is not None:
                        allocations[sid] = shared
                        continue
                    maximum = options.max_group_size if options.change_employee_counts else count
                    size = model.new_int_var(0, maximum, f"size_{len(variables)}")
                    variables.append(size)
                    model.add(size <= maximum * choice)
                    if not options.change_employee_counts:
                        model.add(size == count * choice)
                    allocations[sid] = size
                    shared = size
                    people.append(size)
                active = model.new_bool_var(f"active_{len(patterns)}")
                total = sum(allocations.values())
                model.add(total >= active)
                model.add(
                    total
                    <= max(
                        1,
                        sum(
                            options.max_group_size if options.change_employee_counts else c
                            for c in original.allocations.values()
                        ),
                    )
                    * active
                )
                # Rules do not depend on headcount, but empty teams must not be penalized.
                unit = replace(
                    candidate, allocations=dict.fromkeys(candidate.allocations, 1), employee_count=1
                )
                checked = analyzer.analyze(
                    replace(project, groups=[unit]),
                    dates[0],
                    dates[-1],
                    shifts,
                    include_details=False,
                )
                penalties.append(active * len(checked["rule_issues"]))
                masks = {
                    sid: [ScheduleCalendar.works_shift(candidate, sid, d) for d in dates]
                    for sid in allocations
                }
                patterns.append(ExistingPattern(original.id, candidate, choice, allocations, masks))
            model.add_exactly_one(choices)
        if not options.allow_mixed_cycles_per_shift:
            for sid in shifts:
                selectors: dict[tuple[int, ...], cp_model.IntVar] = {}
                for pattern in patterns:
                    candidate, allocation = pattern.group, pattern.allocations
                    if sid not in allocation:
                        continue
                    cycle = tuple(candidate.blocks)
                    if cycle not in selectors:
                        selectors[cycle] = model.new_bool_var(f"cycle_{sid}_{len(selectors)}")
                    model.add(allocation[sid] <= options.max_group_size * selectors[cycle])
                model.add(sum(selectors.values()) <= 1)
        pattern_objective = BusinessModelConstraints.constrain_patterns(
            model,
            project,
            [
                (
                    pattern.group.blocks,
                    size,
                    options.max_group_size
                    if options.change_employee_counts
                    else max(pattern.group.allocations.values(), default=0),
                )
                for pattern in patterns
                for size in pattern.allocations.values()
            ],
        )
        cost_objective = BusinessModelConstraints.constrain_budget(model, project, sum(people))
        model.add(sum(people) <= options.max_employees)
        deficits: list[cp_model.IntVar] = []
        hours: list[cp_model.IntVar] = []
        surplus: list[cp_model.IntVar] = []
        for shift in project.shifts:
            for di, day in enumerate(dates):
                if monotonic() >= deadline:
                    return None
                required = shift.demand_by_date.get(
                    day.isoformat(), shift.demand_by_weekday[day.weekday()]
                )
                terms = [
                    (pattern.group, pattern.allocations[shift.id])
                    for pattern in patterns
                    if shift.id in pattern.allocations
                    and pattern.working_days_by_shift[shift.id][di]
                ]
                supplied = sum(size for _, size in terms)
                deficit = model.new_int_var(0, required, f"d_{shift.id}_{di}")
                excess = model.new_int_var(0, options.max_employees, f"s_{shift.id}_{di}")
                model.add_max_equality(deficit, [required - supplied, 0])
                model.add_max_equality(excess, [supplied - required, 0])
                required_minutes = round(required * shift.work_hours * 60)
                missing = model.new_int_var(0, required_minutes, f"h_{shift.id}_{di}")
                provided = sum(
                    size * round(ScheduleCalendar.work_hours(candidate, shift, day) * 60)
                    for candidate, size in terms
                )
                model.add_max_equality(missing, [required_minutes - provided, 0])
                deficits.append(deficit)
                hours.append(missing)
                surplus.append(excess)
        objectives: dict[str, cp_model.LinearExpr | int] = {
            "pattern_count": pattern_objective,
            "monthly_staff_cost": cost_objective,
            "deficit_staff_days": sum(deficits),
            "deficit_work_hours": sum(hours),
            "rule_violation_count": sum(penalties),
            "group_count": len(project.groups),
            "surplus_staff_days": sum(surplus),
            "people_total": sum(people),
        }
        return ExistingGroupsModel(model, patterns, variables, objectives)
