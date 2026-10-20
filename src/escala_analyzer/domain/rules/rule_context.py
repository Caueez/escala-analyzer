"""Shared calendar vocabulary for rule checks."""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.entities import ScheduleGroup, Shift


class RuleContext:
    MONTH_NAMES: ClassVar[list[str]] = [
        "Janeiro",
        "Fevereiro",
        "Março",
        "Abril",
        "Maio",
        "Junho",
        "Julho",
        "Agosto",
        "Setembro",
        "Outubro",
        "Novembro",
        "Dezembro",
    ]

    @staticmethod
    def rotating_hours(group: ScheduleGroup, day: date, shifts: dict[str, Shift]) -> float:
        sid = ScheduleCalendar.shift_on(group, day)
        assert sid is not None
        return ScheduleCalendar.work_hours(group, shifts[sid], day)

    @staticmethod
    def strictest_shift(group: ScheduleGroup, shifts: dict[str, Shift]) -> Shift:
        """Return the longest daily shift assigned to a shared group."""
        shift_ids = group.allocations or {group.shift_id}
        return max(
            (shifts[shift_id] for shift_id in shift_ids),
            key=lambda shift: shift.work_hours,
        )
