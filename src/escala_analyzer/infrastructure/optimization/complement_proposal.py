"""Materialize staffing assignments into additional schedule groups."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from escala_analyzer.domain.contracts.optimization_contracts import CandidatePattern, PatternKey
from escala_analyzer.domain.entities import ProjectState


class ComplementProposalBuilder:
    def __init__(
        self,
        project: ProjectState,
        search_project: ProjectState,
        patterns: list[CandidatePattern],
        by_pattern: dict[PatternKey, list[int]],
        size_count: int,
    ) -> None:
        self.project = project
        self.search_project = search_project
        self.patterns = patterns
        self.by_pattern = by_pattern
        self.sizes = range(size_count)

    def build(self, vector: tuple[int, ...]) -> ProjectState:
        proposal = deepcopy(self.search_project)
        existing_ids = {g.id for g in self.project.groups}
        for (key, indices), number in zip(self.by_pattern.items(), vector[len(self.sizes) :]):
            if not number:
                continue
            buckets: list[dict[str, int]] = [{} for _ in range(number)]
            cursor = 0
            for i in indices:
                sid = self.patterns[i].group.shift_id
                for offset in range(vector[i]):
                    bucket = buckets[(cursor + offset) % number]
                    bucket[sid] = bucket.get(sid, 0) + 1
                cursor = (cursor + vector[i]) % number
            template = self.patterns[indices[0]].group
            for allocations in buckets:
                sid = next(iter(allocations))
                gid = f"complement-{len(proposal.groups)}"
                while gid in existing_ids:
                    gid += "-new"
                existing_ids.add(gid)
                proposal.groups.append(
                    replace(
                        deepcopy(template),
                        id=gid,
                        name=f"Complemento {'x'.join(map(str, key[0]))} · fase {key[1]}",
                        shift_id=sid,
                        employee_count=sum(allocations.values()),
                        allocations=allocations,
                    )
                )
        return proposal
