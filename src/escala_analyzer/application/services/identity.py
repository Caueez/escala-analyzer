"""Identity contracts passed across the HTTP and persistence boundaries."""

from dataclasses import dataclass
from typing import Literal

Role = Literal["admin", "editor", "viewer"]


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    organization_id: str
    role: str
    name: str
    session_id: str
    csrf_hash: str

    @property
    def can_edit(self) -> bool:
        return self.role in {"admin", "editor"}
