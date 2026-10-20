"""Shift: framework-independent domain entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time

from .validation import DomainValidation

WeekdayDemand = list[int]


@dataclass(kw_only=True, slots=True)
class Shift:
    id: str
    name: str
    hours_per_day: float = 8.0
    demand_by_weekday: WeekdayDemand = field(default_factory=lambda: [45] * 7)
    demand_by_date: dict[str, int] = field(default_factory=dict)
    start_time: time | None = None
    break_minutes: int = 0
    hours_include_break: bool = False

    @property
    def work_hours(self) -> float:
        return (
            self.hours_per_day - self.break_minutes / 60
            if self.hours_include_break
            else self.hours_per_day
        )

    @property
    def elapsed_hours(self) -> float:
        return (
            self.hours_per_day
            if self.hours_include_break
            else self.hours_per_day + self.break_minutes / 60
        )

    def validate_duration(self) -> Shift:
        if self.work_hours < 0:
            raise ValueError("O intervalo não pode ser maior que a duração total do turno.")
        if self.elapsed_hours > 24:
            raise ValueError("Horas efetivas e intervalo não podem exceder 24 horas.")
        return self

    @classmethod
    def validate_demand_length(cls, value: WeekdayDemand) -> WeekdayDemand:
        if len(value) != 7:
            raise ValueError("Informe uma demanda para cada dia da semana, de segunda a domingo.")
        if any(item < 0 for item in value):
            raise ValueError("A demanda não pode ser negativa.")
        return value

    @classmethod
    def validate_daily_demand(cls, value: dict[str, int]) -> dict[str, int]:
        for day_text, demand in value.items():
            try:
                date.fromisoformat(day_text)
            except ValueError as exc:
                raise ValueError(f"Data de demanda inválida: {day_text}") from exc
            if demand < 0:
                raise ValueError("A demanda não pode ser negativa.")
        return value

    def __post_init__(self) -> None:
        DomainValidation.range("hours_per_day", self.hours_per_day, 0, 24)
        DomainValidation.range("break_minutes", self.break_minutes, 0, 1440)
        self.validate_demand_length(self.demand_by_weekday)
        self.validate_daily_demand(self.demand_by_date)
        self.validate_duration()
