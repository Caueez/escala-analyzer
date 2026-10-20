"""Modelos de domínio e validação dos dados do projeto."""

from __future__ import annotations

from datetime import date, time
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

WeekdayDemand = list[int]


class Shift(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    name: str
    hours_per_day: float = Field(default=8.0, ge=0, le=24)
    # Ordem: segunda, terça, quarta, quinta, sexta, sábado, domingo.
    demand_by_weekday: WeekdayDemand = Field(default_factory=lambda: [45] * 7)
    # Exceções por data (YYYY-MM-DD) têm prioridade sobre a demanda semanal.
    demand_by_date: dict[str, int] = Field(default_factory=dict)
    start_time: time | None = None
    break_minutes: int = Field(default=0, ge=0, le=1440)
    # Backups antigos informavam trabalho efetivo; não reinterpretar seus valores.
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

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_shift(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = {
                key: item
                for key, item in value.items()
                if key not in {"journey_id", "monthly_employee_cost", "overtime_hour_cost"}
            }
        return value

    @model_validator(mode="after")
    def validate_duration(self) -> Shift:
        if self.work_hours < 0:
            raise ValueError("O intervalo não pode ser maior que a duração total do turno.")
        if self.elapsed_hours > 24:
            raise ValueError("Horas efetivas e intervalo não podem exceder 24 horas.")
        return self

    @field_validator("demand_by_weekday")
    @classmethod
    def validate_demand_length(cls, value: WeekdayDemand) -> WeekdayDemand:
        if len(value) != 7:
            raise ValueError("Informe uma demanda para cada dia da semana, de segunda a domingo.")
        if any(item < 0 for item in value):
            raise ValueError("A demanda não pode ser negativa.")
        return value

    @field_validator("demand_by_date")
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


OptimizationPriority = Literal[
    "deficit_staff_days",
    "deficit_work_hours",
    "rule_violation_count",
    "pattern_count",
    "monthly_staff_cost",
    "group_count",
    "surplus_staff_days",
    "people_total",
]

OPTIMIZATION_PRIORITIES: tuple[OptimizationPriority, ...] = (
    "deficit_staff_days",
    "deficit_work_hours",
    "rule_violation_count",
    "pattern_count",
    "monthly_staff_cost",
    "group_count",
    "surplus_staff_days",
    "people_total",
)


class ScheduleGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    name: str
    # Campos legados, preservados para que backups das versões anteriores abram.
    shift_id: str = ""
    employee_count: int = Field(default=1, ge=0, le=100_000)
    # Um mesmo padrão de grupo pode ser usado em vários turnos. A chave é o id
    # do turno e o valor é a quantidade de pessoas daquele grupo nele.
    allocations: dict[str, int] = Field(default_factory=dict)
    automatic_shift_ids: set[str] = Field(default_factory=set)
    work_days: int = Field(default=3, ge=1)
    rest_days: int = Field(default=1, ge=1)
    cycle_blocks: list[int] | None = None
    cycle_days: int | None = Field(default=None, ge=1)

    @property
    def blocks(self) -> list[int]:
        return self.cycle_blocks or [self.work_days, self.rest_days]

    @property
    def cycle_length(self) -> int:
        return sum(self.blocks)

    @field_validator("cycle_blocks")
    @classmethod
    def validate_blocks(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and (not value or any(n < 1 for n in value)):
            raise ValueError("Cada bloco do ciclo deve ter ao menos um dia.")
        return value

    @model_validator(mode="after")
    def validate_cycle_total(self) -> ScheduleGroup:
        if self.cycle_days is not None and self.cycle_days != self.cycle_length:
            raise ValueError("A soma dos blocos deve coincidir com o total de dias do ciclo.")
        return self

    # A data de referência é o primeiro dia TRABALHADO de um ciclo.
    cycle_anchor: date = date(2026, 1, 1)
    cycle_anchor_weekday: int | None = Field(default=None, ge=0, le=6)
    cycle_phase_offset: int = 0
    layer_by_shift: dict[str, int] = Field(default_factory=dict)
    # Sobrescritas pontuais: chave ISO YYYY-MM-DD; true=trabalho, false=folga.
    overrides: dict[str, bool] = Field(default_factory=dict)
    # Uma única equipe alterna de turno a cada ciclo completo; alocações comuns
    # continuam representando equipes distintas com o mesmo padrão de folgas.
    rotation_shift_ids: list[str] = Field(default_factory=list)

    # Horas efetivas (sem pausa), Seg a Dom. None herda o turno; zero é folga.
    work_hours_by_weekday: list[float | None] = Field(default_factory=lambda: [None] * 7)
    min_hours_by_weekday: list[float] = Field(default_factory=lambda: [6.0] * 7)
    max_hours_by_weekday: list[float] = Field(default_factory=lambda: [8.0] * 7)
    allow_hours_optimization: bool = False

    @field_validator("work_hours_by_weekday", "min_hours_by_weekday", "max_hours_by_weekday")
    @classmethod
    def validate_weekly_hours(cls, value: list[float | None]) -> list[float | None]:
        import math

        if len(value) != 7 or any(
            v is not None and (not math.isfinite(v) or v < 0 or v > 24) for v in value
        ):
            raise ValueError("Informe sete jornadas entre 0 e 24 horas, de segunda a domingo.")
        return value

    @model_validator(mode="after")
    def validate_hour_bounds(self) -> ScheduleGroup:
        if any(
            low > high for low, high in zip(self.min_hours_by_weekday, self.max_hours_by_weekday)
        ):
            raise ValueError("O mínimo de horas não pode ultrapassar o máximo do dia.")
        return self

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

    @field_validator("allocations")
    @classmethod
    def validate_allocations(cls, value: dict[str, int]) -> dict[str, int]:
        if any(not shift_id or count < 0 or count > 100_000 for shift_id, count in value.items()):
            raise ValueError("As alocações dos grupos precisam ter turno e quantidade válidos.")
        return value

    @model_validator(mode="after")
    def migrate_legacy_allocation(self) -> ScheduleGroup:
        if not self.allocations and self.shift_id:
            self.allocations = {self.shift_id: self.employee_count}
        if self.allocations and self.shift_id not in self.allocations:
            self.shift_id = next(iter(self.allocations))
        return self

    def staff_for(self, shift_id: str) -> int:
        return self.allocations.get(shift_id, 0)


class RuleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    profile: Literal["baseline", "transition", "target"] = "transition"
    profile_label: str = "Cenário de transição proposto — validar antes de aplicar"
    weekly_max_hours: float = Field(default=42.0, ge=0, le=168)
    min_rest_days_in_rolling_7: int = Field(default=2, ge=0, le=7)
    min_sundays_off_per_month: int = Field(default=1, ge=0, le=5)
    min_days_off_per_month: int = Field(default=8, ge=0, le=31)
    check_min_days_off_per_month: bool = True
    max_consecutive_work_days: int = Field(default=5, ge=1, le=31)
    min_intershift_hours: float = Field(default=11, ge=0, le=168)
    check_intershift_rest: bool = False
    min_break_over_6h_minutes: int = Field(default=60, ge=0, le=240)
    min_break_over_4h_minutes: int = Field(default=15, ge=0, le=240)
    check_breaks: bool = False


class RulePeriod(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    effective_from: date
    label: str = Field(min_length=1)
    source: str = ""
    rules: RuleSettings


class CompanySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    country: Literal["BR"] = "BR"
    state: str = ""
    city: str = ""
    sector: str = ""
    category: str = ""
    collective_agreement: str = ""


class BusinessConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    max_schedule_patterns: int | None = Field(default=2, ge=1, le=200)
    min_work_percent: float = Field(default=50, ge=0, le=100, allow_inf_nan=False)
    max_consecutive_rest_days: int | None = Field(default=3, ge=1)
    monthly_employee_cost: float = Field(default=0, ge=0, le=1_000_000_000, allow_inf_nan=False)
    monthly_budget: float | None = Field(
        default=None, ge=0, le=1_000_000_000_000, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def validate_budget(self) -> BusinessConstraints:
        if self.monthly_budget is not None and self.monthly_employee_cost <= 0:
            raise ValueError(
                "Informe um custo mensal por funcionário positivo para limitar o orçamento."
            )
        return self


class ProjectState(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    project_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=36)
    portfolio_id: str = "legacy"
    portfolio_name: str = "Fiação 2027"
    search_options: dict[str, JsonValue] = Field(default_factory=dict)
    shared_group_links: dict[str, str] = Field(default_factory=dict)
    name: str = "Nova escala"
    year: int = Field(default_factory=lambda: date.today().year, ge=2000, le=2100)
    # 0 representa a visualização contínua do ano inteiro na interface.
    selected_month: int = Field(default=1, ge=0, le=12)
    shifts: list[Shift] = Field(default_factory=list)
    groups: list[ScheduleGroup] = Field(default_factory=list)
    rules: RuleSettings = Field(default_factory=RuleSettings)
    company: CompanySettings = Field(default_factory=CompanySettings)
    rule_periods: list[RulePeriod] = Field(default_factory=list)
    optimization_priorities: list[OptimizationPriority] = Field(
        default_factory=lambda: list(OPTIMIZATION_PRIORITIES)
    )
    business_constraints: BusinessConstraints = Field(default_factory=BusinessConstraints)
    notes: str = ""

    @field_validator("optimization_priorities", mode="before")
    @classmethod
    def validate_priorities(cls, value: list[str]) -> list[str]:
        legacy = set(OPTIMIZATION_PRIORITIES) - {"pattern_count", "monthly_staff_cost"}
        if len(value) == len(legacy) and set(value) == legacy:
            value = [*value, "pattern_count", "monthly_staff_cost"]
        if len(value) != len(OPTIMIZATION_PRIORITIES) or set(value) != set(OPTIMIZATION_PRIORITIES):
            raise ValueError("Ordene todos os critérios de aceitação, sem repetições.")
        return value

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_project(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = {
                key: item for key, item in value.items() if key not in {"journeys", "planning"}
            }
        return value

    def rules_on(self, day: date) -> RuleSettings:
        applicable = [p for p in self.rule_periods if p.effective_from <= day]
        return max(applicable, key=lambda p: p.effective_from).rules if applicable else self.rules

    @model_validator(mode="after")
    def validate_references(self) -> ProjectState:
        dates = [period.effective_from for period in self.rule_periods]
        if len(dates) != len(set(dates)):
            raise ValueError("Duas regras não podem iniciar na mesma data.")
        shift_ids = [shift.id for shift in self.shifts]
        if len(shift_ids) != len(set(shift_ids)):
            raise ValueError("Existem turnos com identificadores duplicados.")

        group_ids = [group.id for group in self.groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("Existem grupos com identificadores duplicados.")

        valid_shift_ids = set(shift_ids)
        for group in self.groups:
            if group.rotation_shift_ids:
                if set(group.allocations) != set(group.rotation_shift_ids):
                    raise ValueError("As alocações devem coincidir com os turnos de revezamento.")
                if len(set(group.rotation_shift_ids)) != len(group.rotation_shift_ids):
                    raise ValueError("Os turnos de revezamento não podem se repetir.")
                if not set(group.rotation_shift_ids) <= valid_shift_ids:
                    raise ValueError("O revezamento referencia um turno que não existe.")
                if any(
                    group.staff_for(sid) != group.employee_count for sid in group.rotation_shift_ids
                ):
                    raise ValueError(
                        "A equipe rotativa deve ter o mesmo tamanho em todos os turnos."
                    )
            if not group.automatic_shift_ids <= set(group.allocations):
                raise ValueError(
                    f'O grupo "{group.name}" tem alocação automática em turno não alocado.'
                )
            for sid in group.allocations:
                shift = next((s for s in self.shifts if s.id == sid), None)
                if shift and any(
                    h is not None and h > 0 and h + shift.break_minutes / 60 > 24
                    for h in group.work_hours_by_weekday
                ):
                    raise ValueError(
                        f'A jornada do grupo "{group.name}" somada à pausa do turno excede 24 horas.'
                    )
            referenced_shift_ids = set(group.allocations) or {group.shift_id}
            if not referenced_shift_ids <= valid_shift_ids:
                raise ValueError(f'O grupo "{group.name}" referencia um turno que não existe.')
        return self
