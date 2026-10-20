"""BusinessConstraints: framework-independent domain entity."""

from __future__ import annotations

from dataclasses import dataclass

from .validation import DomainValidation


@dataclass(kw_only=True, slots=True)
class BusinessConstraints:
    max_schedule_patterns: int | None = 2
    min_work_percent: float = 50
    max_consecutive_rest_days: int | None = 3
    monthly_employee_cost: float = 0
    monthly_budget: float | None = None

    def validate_budget(self) -> BusinessConstraints:
        if self.monthly_budget is not None and self.monthly_employee_cost <= 0:
            raise ValueError(
                "Informe um custo mensal por funcionário positivo para limitar o orçamento."
            )
        return self

    def __post_init__(self) -> None:
        DomainValidation.range("max_schedule_patterns", self.max_schedule_patterns, 1, 200)
        DomainValidation.range("min_work_percent", self.min_work_percent, 0, 100)
        DomainValidation.range("max_consecutive_rest_days", self.max_consecutive_rest_days, 1, None)
        DomainValidation.range("monthly_employee_cost", self.monthly_employee_cost, 0, 1000000000)
        DomainValidation.range("monthly_budget", self.monthly_budget, 0, 1000000000000)
        self.validate_budget()
