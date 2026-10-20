"""Validated inputs and candidate cycle enumeration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .project import ProjectState


class OptimizationCycle(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    work_days: int = Field(default=3, ge=1)
    rest_days: int = Field(default=1, ge=1)
    cycle_blocks: list[int] | None = None

    @property
    def blocks(self) -> list[int]:
        return self.cycle_blocks or [self.work_days, self.rest_days]

    @model_validator(mode="after")
    def validate_blocks(self) -> OptimizationCycle:
        if self.cycle_blocks is not None and (
            not self.cycle_blocks or any(n < 1 for n in self.cycle_blocks)
        ):
            raise ValueError("Cada bloco deve ter ao menos um dia.")
        return self


class OptimizationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    automatic_cycles: bool = True
    max_cycle_days: int = Field(default=7, ge=2, le=14)
    allow_mixed_cycles_per_shift: bool = True
    cycles: list[OptimizationCycle] = Field(
        default_factory=lambda: [
            OptimizationCycle(work_days=w, rest_days=r) for w, r in [(5, 2), (4, 2), (3, 2), (2, 2)]
        ],
        min_length=1,
    )
    max_group_size: int = Field(default=100, ge=1, le=100_000)
    max_employees: int = Field(default=1000, ge=0, le=100_000)
    max_groups: int = Field(default=40, ge=0, le=200)
    max_solutions: int = Field(default=10, ge=1, le=30)
    time_limit_seconds: float = Field(default=20, ge=1, le=60, allow_inf_nan=False)

    optimize_existing: bool = False
    change_employee_counts: bool = True
    change_cycles: bool = True
    optimize_work_hours: bool = False
    hours_step_minutes: int = Field(default=15, ge=1, le=60)
    new_group_min_hours: float = Field(default=6, ge=0, le=24, allow_inf_nan=False)
    new_group_max_hours: float = Field(default=8, ge=0, le=24, allow_inf_nan=False)

    @model_validator(mode="after")
    def unique_cycles(self) -> OptimizationOptions:
        if self.new_group_min_hours > self.new_group_max_hours:
            raise ValueError("O mínimo de horas dos novos grupos não pode exceder o máximo.")
        if len({tuple(c.blocks) for c in self.cycles}) != len(self.cycles):
            raise ValueError("Não repita os ciclos candidatos.")
        return self


class OptimizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    project: ProjectState
    options: OptimizationOptions = Field(default_factory=OptimizationOptions)
