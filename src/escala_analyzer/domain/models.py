"""Modelos de domínio e validação dos dados do projeto."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WeekdayDemand = list[int]


class Shift(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    hours_per_day: float = Field(default=8.0, ge=0, le=24)
    # Ordem: segunda, terça, quarta, quinta, sexta, sábado, domingo.
    demand_by_weekday: WeekdayDemand = Field(default_factory=lambda: [45] * 7)

    @field_validator("demand_by_weekday")
    @classmethod
    def validate_demand_length(cls, value: WeekdayDemand) -> WeekdayDemand:
        if len(value) != 7:
            raise ValueError("Informe uma demanda para cada dia da semana, de segunda a domingo.")
        if any(item < 0 for item in value):
            raise ValueError("A demanda não pode ser negativa.")
        return value


class ScheduleGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    shift_id: str
    employee_count: int = Field(default=1, ge=0, le=100_000)
    work_days: int = Field(default=3, ge=1, le=31)
    rest_days: int = Field(default=1, ge=1, le=31)
    # A data de referência é o primeiro dia TRABALHADO de um ciclo.
    cycle_anchor: date = date(2026, 1, 1)
    # Sobrescritas pontuais: chave ISO YYYY-MM-DD; true=trabalho, false=folga.
    overrides: dict[str, bool] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("O nome do grupo não pode ficar vazio.")
        return cleaned

    @field_validator("overrides")
    @classmethod
    def validate_override_dates(cls, value: dict[str, bool]) -> dict[str, bool]:
        for date_text in value:
            try:
                date.fromisoformat(date_text)
            except ValueError as exc:
                raise ValueError(f"Data de ajuste inválida: {date_text}") from exc
        return value


class RuleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: Literal["baseline", "transition", "target"] = "transition"
    profile_label: str = "Cenário de transição proposto — validar antes de aplicar"
    weekly_max_hours: float = Field(default=42.0, ge=0, le=168)
    min_rest_days_in_rolling_7: int = Field(default=2, ge=0, le=7)
    min_sundays_off_per_month: int = Field(default=1, ge=0, le=5)
    min_days_off_per_month: int = Field(default=8, ge=0, le=31)
    check_min_days_off_per_month: bool = True
    max_consecutive_work_days: int = Field(default=5, ge=1, le=31)


class ProjectState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "Fiação — modelo inicial editável"
    year: int = Field(default=2027, ge=2000, le=2100)
    selected_month: int = Field(default=1, ge=1, le=12)
    shifts: list[Shift] = Field(default_factory=list)
    groups: list[ScheduleGroup] = Field(default_factory=list)
    rules: RuleSettings = Field(default_factory=RuleSettings)
    notes: str = (
        "Os números iniciais são apenas demonstrativos. Substitua-os pelos dados reais "
        "e valide as regras com RH, sindicato ou assessoria jurídica."
    )

    @model_validator(mode="after")
    def validate_references(self) -> ProjectState:
        shift_ids = [shift.id for shift in self.shifts]
        if len(shift_ids) != len(set(shift_ids)):
            raise ValueError("Existem turnos com identificadores duplicados.")

        group_ids = [group.id for group in self.groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("Existem grupos com identificadores duplicados.")

        valid_shift_ids = set(shift_ids)
        for group in self.groups:
            if group.shift_id not in valid_shift_ids:
                raise ValueError(
                    f'O grupo "{group.name}" referencia um turno que não existe.'
                )
        return self
