"""Business search preferences and cycle enumeration, independent of solvers."""

from __future__ import annotations

from dataclasses import dataclass

from escala_analyzer.domain.entities.validation import DomainValidation


@dataclass(kw_only=True, slots=True)
class OptimizationCycle:
    work_days: int = 3
    rest_days: int = 1
    cycle_blocks: list[int] | None = None

    @property
    def blocks(self) -> list[int]:
        return self.cycle_blocks or [self.work_days, self.rest_days]

    def validate_blocks(self) -> OptimizationCycle:
        if self.cycle_blocks is not None and (
            not self.cycle_blocks or any(n < 1 for n in self.cycle_blocks)
        ):
            raise ValueError("Cada bloco deve ter ao menos um dia.")
        return self

    def __post_init__(self) -> None:
        DomainValidation.range("work_days", self.work_days, 1, None)
        DomainValidation.range("rest_days", self.rest_days, 1, None)
        self.validate_blocks()


@dataclass(kw_only=True, slots=True)
class OptimizationOptions:
    automatic_cycles: bool | None = None
    max_cycle_days: int = 7
    allow_mixed_cycles_per_shift: bool = True
    cycles: list[OptimizationCycle] | None = None
    max_group_size: int = 100
    max_employees: int = 1000
    max_groups: int = 40
    max_solutions: int = 10
    time_limit_seconds: float = 20
    optimize_existing: bool = False
    change_employee_counts: bool = True
    change_cycles: bool = True
    optimize_work_hours: bool = False
    hours_step_minutes: int = 15
    new_group_min_hours: float = 6
    new_group_max_hours: float = 8

    def candidate_cycles(self) -> list[OptimizationCycle]:
        assert self.cycles is not None
        if not self.automatic_cycles:
            return self.cycles
        return CycleCatalog().generate(self.max_cycle_days)

    def unique_cycles(self) -> OptimizationOptions:
        assert self.cycles is not None
        if self.new_group_min_hours > self.new_group_max_hours:
            raise ValueError("O mínimo de horas dos novos grupos não pode exceder o máximo.")
        if len({tuple(c.blocks) for c in self.cycles}) != len(self.cycles):
            raise ValueError("Não repita os ciclos candidatos.")
        return self

    def __post_init__(self) -> None:
        supplied_cycles = self.cycles is not None
        if self.automatic_cycles is None:
            self.automatic_cycles = not supplied_cycles
        if self.cycles is None:
            self.cycles = [
                OptimizationCycle(work_days=w, rest_days=r)
                for w, r in [(5, 2), (4, 2), (3, 2), (2, 2)]
            ]
        DomainValidation.range("max_cycle_days", self.max_cycle_days, 2, 14)
        DomainValidation.length("cycles", self.cycles, 1)
        DomainValidation.range("max_group_size", self.max_group_size, 1, 100000)
        DomainValidation.range("max_employees", self.max_employees, 0, 100000)
        DomainValidation.range("max_groups", self.max_groups, 0, 200)
        DomainValidation.range("max_solutions", self.max_solutions, 1, 30)
        DomainValidation.range("time_limit_seconds", self.time_limit_seconds, 1, 60)
        DomainValidation.range("hours_step_minutes", self.hours_step_minutes, 1, 60)
        DomainValidation.range("new_group_min_hours", self.new_group_min_hours, 0, 24)
        DomainValidation.range("new_group_max_hours", self.new_group_max_hours, 0, 24)
        self.unique_cycles()


class CycleCatalog:
    """Enumerate primitive periodic work/rest cycles without rotated duplicates."""

    def generate(self, max_cycle_days: int) -> list[OptimizationCycle]:
        from itertools import pairwise, product

        seen: set[tuple[int, ...]] = set()
        cycles: list[OptimizationCycle] = []
        for length in range(2, max_cycle_days + 1):
            for middle in product((0, 1), repeat=length - 2):
                bits = (1, *middle, 0)
                if any(
                    length % n == 0 and bits == bits[:n] * (length // n) for n in range(1, length)
                ):
                    continue
                rotations = [bits[i:] + bits[:i] for i in range(length)]
                key = min(rotations)
                if key in seen:
                    continue
                seen.add(key)
                blocks = [1]
                for previous, current in pairwise(bits):
                    if current == previous:
                        blocks[-1] += 1
                    else:
                        blocks.append(1)
                cycles.append(OptimizationCycle(cycle_blocks=blocks))
        return cycles
