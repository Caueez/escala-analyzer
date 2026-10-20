"""CompanySettings: framework-independent domain entity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(kw_only=True, slots=True)
class CompanySettings:
    country: Literal["BR"] = "BR"
    state: str = ""
    city: str = ""
    sector: str = ""
    category: str = ""
    collective_agreement: str = ""

    def __post_init__(self) -> None:
        if self.country != "BR":
            raise ValueError("País não suportado.")
