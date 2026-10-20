"""Hour model expressions and deduplicated soft constraints."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from math import floor

from ortools.sat.python import cp_model

from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.entities import ScheduleGroup, Shift

HourKey = tuple[str, int]


class HourExpressions:
    def __init__(
        self,
        model: cp_model.CpModel,
        variables: dict[HourKey, cp_model.IntVar],
        presence: dict[HourKey, cp_model.IntVar],
        base_groups: dict[str, ScheduleGroup],
        shifts: dict[str, Shift],
        step: int,
    ) -> None:
        self.model = model
        self.variables = variables
        self.presence = presence
        self.base_groups = base_groups
        self.shifts = shifts
        self.step = step
        self.penalties: list[cp_model.IntVar] = []
        self.constraint_keys: set[tuple[str, int, tuple[str, ...]]] = set()

    def sid_for(self, group: ScheduleGroup, team: str | None, day: date) -> str:
        sid = ScheduleCalendar.shift_on(group, day) if team is None else team
        assert sid is not None
        return sid

    def active(self, group: ScheduleGroup, day: date) -> cp_model.IntVar | int:
        base = self.base_groups.get(group.id, group)
        if not ScheduleCalendar.is_working(base, day):
            return 0
        return self.presence[group.id, day.weekday()] if group.id in self.base_groups else 1

    def minutes(self, group: ScheduleGroup, day: date, sid: str) -> cp_model.LinearExpr | int:
        if not ScheduleCalendar.is_working(self.base_groups.get(group.id, group), day):
            return 0
        if group.id in self.base_groups:
            return self.variables[group.id, day.weekday()] * self.step
        return round(ScheduleCalendar.work_hours(group, self.shifts[sid], day) * 60)

    def soft_le(
        self,
        expr: cp_model.LinearExpr | int,
        maximum: float,
        enabled: Sequence[cp_model.IntVar | int] = (),
    ) -> None:
        key = (str(expr), round(maximum), tuple(str(v) for v in enabled))
        if key in self.constraint_keys:
            return
        self.constraint_keys.add(key)
        violation = self.model.new_bool_var(f"rule_{len(self.penalties)}")
        self.model.add(expr <= floor(maximum + 1e-9)).only_enforce_if([violation.Not(), *enabled])
        self.penalties.append(violation)
