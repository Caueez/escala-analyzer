
"""Operações de calendário e ciclos de trabalho."""

from __future__ import annotations

from datetime import date, timedelta

from .models import ScheduleGroup


class ScheduleCalendar:
    """Interpreta os ciclos de trabalho e os ajustes manuais de um grupo."""

    @staticmethod
    def is_working(group: ScheduleGroup, day: date) -> bool:
        """Retorna se o grupo trabalha na data, respeitando ajustes manuais."""
        override = group.overrides.get(day.isoformat())

        if override is not None:
            return override

        cycle_length = group.work_days + group.rest_days
        cycle_position = (day - group.cycle_anchor).days % cycle_length

        return cycle_position < group.work_days

    @staticmethod
    def month_dates(year: int, month: int) -> list[date]:
        """Retorna todas as datas de um mês."""
        first_day = date(year, month, 1)

        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)

        days_count = (next_month - first_day).days

        return [
            first_day + timedelta(days=offset)
            for offset in range(days_count)
        ]

    @staticmethod
    def year_dates(year: int) -> list[date]:
        """Retorna todas as datas de um ano."""
        first_day = date(year, 1, 1)
        next_year = date(year + 1, 1, 1)
        days_count = (next_year - first_day).days

        return [
            first_day + timedelta(days=offset)
            for offset in range(days_count)
        ]
