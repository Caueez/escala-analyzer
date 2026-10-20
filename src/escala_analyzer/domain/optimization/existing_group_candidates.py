"""Enumerate permitted cycle and phase changes without losing group identity."""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from dataclasses import replace
from itertools import zip_longest
from time import monotonic

from escala_analyzer.domain.entities import ScheduleGroup
from escala_analyzer.domain.optimization.optimization_options import OptimizationOptions


class ExistingGroupCandidateFactory:
    def create(
        self, original: ScheduleGroup, options: OptimizationOptions, candidate_deadline: float
    ) -> Iterator[ScheduleGroup]:
        yield deepcopy(original)
        if not options.change_cycles:
            return
        blocks_options = [
            original.blocks,
            *(cycle.blocks for cycle in options.candidate_cycles()),
        ]
        blocks_options = list(dict.fromkeys(tuple(blocks) for blocks in blocks_options))
        blocks_options = [
            blocks
            for blocks in blocks_options
            if original.cycle_days is None or sum(blocks) == original.cycle_days
        ]
        seen = {
            (
                tuple(original.blocks),
                original.cycle_phase_offset
                % (original.cycle_length * max(1, len(original.rotation_shift_ids))),
            )
        }
        # Interleave cycles so a very long pattern cannot consume the entire budget.
        for phases in zip_longest(
            *(
                range(sum(blocks) * max(1, len(original.rotation_shift_ids)))
                for blocks in blocks_options
            )
        ):
            for blocks, phase in zip(blocks_options, phases):
                if monotonic() >= candidate_deadline:
                    return
                if phase is None or (blocks, phase) in seen:
                    continue
                seen.add((blocks, phase))
                yield replace(
                    deepcopy(original), cycle_blocks=list(blocks), cycle_phase_offset=phase
                )
