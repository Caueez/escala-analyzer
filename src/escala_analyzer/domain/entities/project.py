"""ProjectState: framework-independent domain entity."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from uuid import uuid4

from ..contracts.types import OPTIMIZATION_PRIORITIES, JsonValue, OptimizationPriority
from .business_constraints import BusinessConstraints
from .company_settings import CompanySettings
from .rule_period import RulePeriod
from .rule_settings import RuleSettings
from .schedule_group import ScheduleGroup
from .shift import Shift
from .validation import DomainValidation


@dataclass(kw_only=True, slots=True)
class ProjectState:
    project_id: str = field(default_factory=lambda: str(uuid4()))
    portfolio_id: str = "legacy"
    portfolio_name: str = "Fiação 2027"
    search_options: dict[str, JsonValue] = field(default_factory=dict)
    shared_group_links: dict[str, str] = field(default_factory=dict)
    name: str = "Nova escala"
    year: int = field(default_factory=lambda: date.today().year)
    selected_month: int = 1
    shifts: list[Shift] = field(default_factory=list)
    groups: list[ScheduleGroup] = field(default_factory=list)
    rules: RuleSettings = field(default_factory=RuleSettings)
    company: CompanySettings = field(default_factory=CompanySettings)
    rule_periods: list[RulePeriod] = field(default_factory=list)
    optimization_priorities: list[OptimizationPriority] = field(
        default_factory=lambda: list(OPTIMIZATION_PRIORITIES)
    )
    business_constraints: BusinessConstraints = field(default_factory=BusinessConstraints)
    notes: str = ""

    @classmethod
    def validate_priorities(
        cls, value: Sequence[OptimizationPriority]
    ) -> list[OptimizationPriority]:
        value = list(value)
        legacy = set(OPTIMIZATION_PRIORITIES) - {"pattern_count", "monthly_staff_cost"}
        if len(value) == len(legacy) and set(value) == legacy:
            value = [*value, "pattern_count", "monthly_staff_cost"]
        if len(value) != len(OPTIMIZATION_PRIORITIES) or set(value) != set(OPTIMIZATION_PRIORITIES):
            raise ValueError("Ordene todos os critérios de aceitação, sem repetições.")
        return value

    def rules_on(self, day: date) -> RuleSettings:
        applicable = [p for p in self.rule_periods if p.effective_from <= day]
        return max(applicable, key=lambda p: p.effective_from).rules if applicable else self.rules

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
                    h is not None and h > 0 and (h + shift.break_minutes / 60 > 24)
                    for h in group.work_hours_by_weekday
                ):
                    raise ValueError(
                        f'A jornada do grupo "{group.name}" somada à pausa do turno excede 24 horas.'
                    )
            referenced_shift_ids = set(group.allocations) or {group.shift_id}
            if not referenced_shift_ids <= valid_shift_ids:
                raise ValueError(f'O grupo "{group.name}" referencia um turno que não existe.')
        return self

    def __post_init__(self) -> None:
        DomainValidation.range("year", self.year, 2000, 2100)
        DomainValidation.range("selected_month", self.selected_month, 0, 12)
        self.optimization_priorities = self.validate_priorities(self.optimization_priorities)
        self.validate_references()
