"""Generate and assess candidate cycles for each shift."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from time import monotonic

from escala_analyzer.domain.analysis.schedule_rules_analyzer import ScheduleRulesAnalyzer
from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.contracts.optimization_contracts import CandidatePattern
from escala_analyzer.domain.entities import ProjectState, ScheduleGroup
from escala_analyzer.domain.optimization.optimization_options import OptimizationOptions
from escala_analyzer.domain.policies.business_constraints import BusinessPolicy


class CandidatePatternFactory:
    def create(
        self, project: ProjectState, options: OptimizationOptions, deadline: float
    ) -> list[CandidatePattern] | None:
        dates = ScheduleCalendar.year_dates(project.year)
        shifts = {shift.id: shift for shift in project.shifts}
        patterns: list[CandidatePattern] = []
        rule_analyzer = ScheduleRulesAnalyzer()
        for shift in project.shifts:
            for cycle in options.candidate_cycles():
                if not BusinessPolicy.allowed_cycle(cycle.blocks, project.business_constraints):
                    continue
                for phase in range(sum(cycle.blocks)):
                    if monotonic() >= deadline:
                        return None
                    group = ScheduleGroup(
                        id="candidate",
                        name="Candidato",
                        shift_id=shift.id,
                        allocations={shift.id: 1},
                        cycle_blocks=cycle.cycle_blocks,
                        work_days=cycle.work_days,
                        rest_days=cycle.rest_days,
                        cycle_anchor=date(project.year, 1, 1),
                        cycle_phase_offset=phase,
                        allow_hours_optimization=options.optimize_work_hours,
                        min_hours_by_weekday=[options.new_group_min_hours] * 7,
                        max_hours_by_weekday=[options.new_group_max_hours] * 7,
                        work_hours_by_weekday=[
                            min(options.new_group_max_hours, 24 - shift.break_minutes / 60)
                        ]
                        * 7
                        if options.optimize_work_hours
                        else [None] * 7,
                    )
                    candidate = replace(project, groups=[group])
                    checked = rule_analyzer.analyze(
                        candidate, dates[0], dates[-1], shifts, include_details=False
                    )
                    patterns.append(
                        CandidatePattern(
                            group,
                            [ScheduleCalendar.is_working(group, day) for day in dates],
                            len(checked["rule_issues"]),
                        )
                    )
        return patterns
