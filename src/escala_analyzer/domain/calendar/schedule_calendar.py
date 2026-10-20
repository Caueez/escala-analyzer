"""Operações de calendário e ciclos de trabalho."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from escala_analyzer.domain.entities import ScheduleGroup, Shift


class ScheduleCalendar:
    """Interpreta os ciclos de trabalho e os ajustes manuais de um grupo."""

    @staticmethod
    def is_working(group: ScheduleGroup, day: date) -> bool:
        """Retorna se o grupo trabalha na data, respeitando ajustes manuais."""
        if group.work_hours_by_weekday[day.weekday()] == 0:
            return False
        override = group.overrides.get(day.isoformat())

        if override is not None:
            return override

        cycle_length = group.cycle_length
        anchor = group.cycle_anchor
        if group.cycle_anchor_weekday is not None:
            # Segunda-feira de 01/01/2024 é uma referência fixa. A fase do
            # ciclo não pode ser recalculada a cada semana, pois isso faria um
            # 3x1 parecer 6x1 ao cruzar a segunda-feira.
            anchor = date(2024, 1, 1) + timedelta(days=group.cycle_anchor_weekday)
        cycle_position = (day - anchor).days + group.cycle_phase_offset
        cycle_position %= cycle_length

        for index, length in enumerate(group.blocks):
            if cycle_position < length:
                return index % 2 == 0
            cycle_position -= length
        return False

    @staticmethod
    def shift_on(group: ScheduleGroup, day: date) -> str | None:
        if not group.rotation_shift_ids:
            return None
        anchor = group.cycle_anchor
        if group.cycle_anchor_weekday is not None:
            anchor = date(2024, 1, 1) + timedelta(days=group.cycle_anchor_weekday)
        cycle = ((day - anchor).days + group.cycle_phase_offset) // (group.cycle_length)
        return group.rotation_shift_ids[cycle % len(group.rotation_shift_ids)]

    @staticmethod
    def works_shift(group: ScheduleGroup, shift_id: str, day: date) -> bool:
        return ScheduleCalendar.is_working(group, day) and (
            not group.rotation_shift_ids or ScheduleCalendar.shift_on(group, day) == shift_id
        )

    @staticmethod
    def work_hours(group: ScheduleGroup, shift: Shift, day: date) -> float:
        configured = group.work_hours_by_weekday[day.weekday()]
        return shift.work_hours if configured is None else configured

    @staticmethod
    def effective_shift(group: ScheduleGroup, shift: Shift, day: date) -> Shift:
        return replace(
            shift,
            hours_per_day=ScheduleCalendar.work_hours(group, shift, day),
            hours_include_break=False,
        )

    @staticmethod
    def month_dates(year: int, month: int) -> list[date]:
        """Retorna todas as datas de um mês."""
        first_day = date(year, month, 1)

        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)

        days_count = (next_month - first_day).days

        return [first_day + timedelta(days=offset) for offset in range(days_count)]

    @staticmethod
    def year_dates(year: int) -> list[date]:
        """Retorna todas as datas de um ano."""
        first_day = date(year, 1, 1)
        next_year = date(year + 1, 1, 1)
        days_count = (next_year - first_day).days

        return [first_day + timedelta(days=offset) for offset in range(days_count)]
