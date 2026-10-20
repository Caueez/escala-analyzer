"""Translate configured journey rules into hour model penalties."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from math import ceil, floor
from time import monotonic

from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.entities import ProjectState, ScheduleGroup
from escala_analyzer.infrastructure.optimization.hour_expressions import HourExpressions


class HourRuleConstraints:
    def apply(
        self,
        project: ProjectState,
        eligible: list[ScheduleGroup],
        expressions: HourExpressions,
        deadline: float,
    ) -> bool:
        model, step, variables, shifts = (
            expressions.model,
            expressions.step,
            expressions.variables,
            expressions.shifts,
        )
        year_start, year_end = date(project.year, 1, 1), date(project.year, 12, 31)
        dates = ScheduleCalendar.year_dates(project.year)
        for group in eligible:
            fixed_teams = (
                [None]
                if group.rotation_shift_ids
                else [sid for sid, count in group.allocations.items() if count > 0]
            )
            for team in fixed_teams:
                # Windows intersecting the year, matching the independent analyzer.
                day = year_start - timedelta(days=6)
                while day <= year_end:
                    window = [day + timedelta(days=i) for i in range(7)]
                    rules = project.rules_on(window[-1])
                    work = sum(
                        expressions.minutes(group, d, expressions.sid_for(group, team, d))
                        for d in window
                    )
                    expressions.soft_le(work, rules.weekly_max_hours * 60)
                    expressions.soft_le(
                        sum(expressions.active(group, d) for d in window),
                        7 - rules.min_rest_days_in_rolling_7,
                    )
                    day += timedelta(days=1)
                for month in range(1, 13):
                    month_days = ScheduleCalendar.month_dates(project.year, month)
                    rules = [project.rules_on(d) for d in month_days]
                    monthly_rest = max(
                        (r.min_days_off_per_month if r.check_min_days_off_per_month else 0)
                        for r in rules
                    )
                    sundays = [d for d in month_days if d.weekday() == 6]
                    expressions.soft_le(
                        sum(expressions.active(group, d) for d in month_days),
                        len(month_days) - monthly_rest,
                    )
                    expressions.soft_le(
                        sum(expressions.active(group, d) for d in sundays),
                        len(sundays) - max(r.min_sundays_off_per_month for r in rules),
                    )
                for day in dates:
                    if monotonic() >= deadline:
                        return False
                    rules = project.rules_on(day)
                    cap = rules.max_consecutive_work_days
                    expressions.soft_le(
                        sum(
                            expressions.active(group, day - timedelta(days=i))
                            for i in range(cap + 1)
                        ),
                        cap,
                    )
                    sid = expressions.sid_for(group, team, day)
                    shift = shifts[sid]
                    on = expressions.active(group, day)
                    if isinstance(on, int) and on == 0:
                        continue
                    if rules.check_breaks:
                        # Validity is evaluated for each possible step, using net work.
                        invalid = model.new_bool_var(f"break_{group.id}_{team}_{day}")
                        var = variables[group.id, day.weekday()]
                        low = ceil(group.min_hours_by_weekday[day.weekday()] * 60 / step - 1e-9)
                        high = min(
                            floor(group.max_hours_by_weekday[day.weekday()] * 60 / step + 1e-9),
                            min(
                                (1440 - shifts[s].break_minutes) // step
                                for s, count in group.allocations.items()
                                if count > 0
                            ),
                        )
                        model.add_allowed_assignments(
                            [var, invalid],
                            [
                                (
                                    u,
                                    int(
                                        shift.break_minutes
                                        < (
                                            rules.min_break_over_6h_minutes
                                            if u * step > 360
                                            else rules.min_break_over_4h_minutes
                                            if u * step > 240
                                            else 0
                                        )
                                    ),
                                )
                                for u in range(low, high + 1)
                            ],
                        )
                        expressions.penalties.append(invalid)
                    if not rules.check_intershift_rest or shift.start_time is None:
                        continue
                    current_start = datetime.combine(day, shift.start_time)
                    # Checking all close pairs also catches consecutive actual shifts
                    # when some weekdays are turned into rest days by a zero duration.
                    for offset in range(1, 9):
                        previous_day = day - timedelta(days=offset)
                        previous_on = expressions.active(group, previous_day)
                        if isinstance(previous_on, int) and previous_on == 0:
                            continue
                        previous_sid = expressions.sid_for(group, team, previous_day)
                        previous_shift = shifts[previous_sid]
                        if previous_shift.start_time is None:
                            continue
                        gap = (
                            current_start
                            - datetime.combine(previous_day, previous_shift.start_time)
                        ).total_seconds() / 60
                        available = (
                            gap - previous_shift.break_minutes - rules.min_intershift_hours * 60
                        )
                        if available >= 1440:
                            continue
                        expressions.soft_le(
                            expressions.minutes(group, previous_day, previous_sid),
                            available,
                            [on, previous_on],
                        )
        return True
