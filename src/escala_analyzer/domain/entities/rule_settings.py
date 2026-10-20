"""RuleSettings: framework-independent domain entity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .validation import DomainValidation


@dataclass(kw_only=True, slots=True)
class RuleSettings:
    profile: Literal["baseline", "transition", "target"] = "transition"
    profile_label: str = "Cenário de transição proposto — validar antes de aplicar"
    weekly_max_hours: float = 42.0
    min_rest_days_in_rolling_7: int = 2
    min_sundays_off_per_month: int = 1
    min_days_off_per_month: int = 8
    check_min_days_off_per_month: bool = True
    max_consecutive_work_days: int = 5
    min_intershift_hours: float = 11
    check_intershift_rest: bool = False
    min_break_over_6h_minutes: int = 60
    min_break_over_4h_minutes: int = 15
    check_breaks: bool = False

    def __post_init__(self) -> None:
        if self.profile not in {"baseline", "transition", "target"}:
            raise ValueError("Perfil de regras inválido.")
        DomainValidation.range("weekly_max_hours", self.weekly_max_hours, 0, 168)
        DomainValidation.range("min_rest_days_in_rolling_7", self.min_rest_days_in_rolling_7, 0, 7)
        DomainValidation.range("min_sundays_off_per_month", self.min_sundays_off_per_month, 0, 5)
        DomainValidation.range("min_days_off_per_month", self.min_days_off_per_month, 0, 31)
        DomainValidation.range("max_consecutive_work_days", self.max_consecutive_work_days, 1, 31)
        DomainValidation.range("min_intershift_hours", self.min_intershift_hours, 0, 168)
        DomainValidation.range("min_break_over_6h_minutes", self.min_break_over_6h_minutes, 0, 240)
        DomainValidation.range("min_break_over_4h_minutes", self.min_break_over_4h_minutes, 0, 240)
