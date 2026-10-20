"""RulePeriod: framework-independent domain entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .rule_settings import RuleSettings
from .validation import DomainValidation


@dataclass(kw_only=True, slots=True)
class RulePeriod:
    effective_from: date
    label: str
    source: str = ""
    rules: RuleSettings

    def __post_init__(self) -> None:
        DomainValidation.length("label", self.label, 1)
