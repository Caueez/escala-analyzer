"""ScheduleGroup: framework-independent domain entity."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from .validation import DomainValidation


@dataclass(kw_only=True, slots=True)
class ScheduleGroup:
    id: str
    name: str
    shift_id: str = ""
    employee_count: int = 1
    allocations: dict[str, int] = field(default_factory=dict)
    automatic_shift_ids: set[str] = field(default_factory=set)
    work_days: int = 3
    rest_days: int = 1
    cycle_blocks: list[int] | None = None
    cycle_days: int | None = None
    cycle_anchor: date = date(2026, 1, 1)
    cycle_anchor_weekday: int | None = None
    cycle_phase_offset: int = 0
    layer_by_shift: dict[str, int] = field(default_factory=dict)
    overrides: dict[str, bool] = field(default_factory=dict)
    rotation_shift_ids: list[str] = field(default_factory=list)
    work_hours_by_weekday: list[float | None] = field(default_factory=lambda: [None] * 7)
    min_hours_by_weekday: list[float] = field(default_factory=lambda: [6.0] * 7)
    max_hours_by_weekday: list[float] = field(default_factory=lambda: [8.0] * 7)
    allow_hours_optimization: bool = False

    @property
    def blocks(self) -> list[int]:
        return self.cycle_blocks or [self.work_days, self.rest_days]

    @property
    def cycle_length(self) -> int:
        return sum(self.blocks)

    @classmethod
    def validate_blocks(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and (not value or any(n < 1 for n in value)):
            raise ValueError("Cada bloco do ciclo deve ter ao menos um dia.")
        return value

    def validate_cycle_total(self) -> ScheduleGroup:
        if self.cycle_days is not None and self.cycle_days != self.cycle_length:
            raise ValueError("A soma dos blocos deve coincidir com o total de dias do ciclo.")
        return self

    @classmethod
    def validate_weekly_hours(cls, value: Sequence[float | None]) -> None:
        import math

        if len(value) != 7 or any(
            v is not None and (not math.isfinite(v) or v < 0 or v > 24) for v in value
        ):
            raise ValueError("Informe sete jornadas entre 0 e 24 horas, de segunda a domingo.")

    def validate_hour_bounds(self) -> ScheduleGroup:
        if any(
            (low > high for low, high in zip(self.min_hours_by_weekday, self.max_hours_by_weekday))
        ):
            raise ValueError("O mínimo de horas não pode ultrapassar o máximo do dia.")
        return self

    @classmethod
    def name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("O nome do grupo não pode ficar vazio.")
        return cleaned

    @classmethod
    def validate_override_dates(cls, value: dict[str, bool]) -> dict[str, bool]:
        for date_text in value:
            try:
                date.fromisoformat(date_text)
            except ValueError as exc:
                raise ValueError(f"Data de ajuste inválida: {date_text}") from exc
        return value

    @classmethod
    def validate_allocations(cls, value: dict[str, int]) -> dict[str, int]:
        if any((not shift_id or count < 0 or count > 100000 for shift_id, count in value.items())):
            raise ValueError("As alocações dos grupos precisam ter turno e quantidade válidos.")
        return value

    def normalize_allocations(self) -> ScheduleGroup:
        if not self.allocations and self.shift_id:
            self.allocations = {self.shift_id: self.employee_count}
        if self.allocations and self.shift_id not in self.allocations:
            self.shift_id = next(iter(self.allocations))
        return self

    def staff_for(self, shift_id: str) -> int:
        return self.allocations.get(shift_id, 0)

    def __post_init__(self) -> None:
        DomainValidation.range("employee_count", self.employee_count, 0, 100000)
        DomainValidation.range("work_days", self.work_days, 1, None)
        DomainValidation.range("rest_days", self.rest_days, 1, None)
        DomainValidation.range("cycle_days", self.cycle_days, 1, None)
        DomainValidation.range("cycle_anchor_weekday", self.cycle_anchor_weekday, 0, 6)
        self.validate_blocks(self.cycle_blocks)
        self.validate_weekly_hours(self.work_hours_by_weekday)
        self.validate_weekly_hours(self.min_hours_by_weekday)
        self.validate_weekly_hours(self.max_hours_by_weekday)
        self.name = self.name_not_blank(self.name)
        self.validate_override_dates(self.overrides)
        self.validate_allocations(self.allocations)
        self.validate_cycle_total()
        self.validate_hour_bounds()
        self.normalize_allocations()
