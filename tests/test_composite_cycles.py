from dataclasses import replace
from datetime import timedelta

import pytest
from test_schedule_optimizer import project

from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.entities import ProjectState, ScheduleGroup
from escala_analyzer.infrastructure.optimization.schedule_optimizer import (
    OptimizationCycle,
    OptimizationOptions,
    ScheduleOptimizer,
)
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec


def test_composite_cycle_wraps_odd_blocks_and_negative_offsets():
    group = ScheduleGroup(id="g", name="G", cycle_blocks=[5, 2, 3, 1, 2], cycle_days=13)
    pattern = [True] * 5 + [False] * 2 + [True] * 3 + [False] + [True] * 2
    for offset in range(-30, 31):
        assert (
            ScheduleCalendar.is_working(group, group.cycle_anchor + timedelta(days=offset))
            == pattern[offset % 13]
        )
    group.rotation_shift_ids = ["a", "b"]
    assert ScheduleCalendar.shift_on(group, group.cycle_anchor + timedelta(days=13)) == "b"


def test_optional_total_and_unlimited_blocks_and_block_days():
    blocks = [40, 2] * 40 + [3]
    group = ScheduleGroup(id="g", name="G", cycle_blocks=blocks, cycle_days=sum(blocks))
    assert group.cycle_length == 1683
    assert not ScheduleCalendar.is_working(group, group.cycle_anchor + timedelta(days=40))
    assert ScheduleGroup(id="g", name="G", work_days=90, rest_days=40).cycle_length == 130
    for invalid in [[], [1, 0, 2], [-1, 2]]:
        with pytest.raises(ValueError):
            ScheduleGroup(id="g", name="G", cycle_blocks=invalid)
    with pytest.raises(ValueError, match="soma"):
        ScheduleGroup(id="g", name="G", cycle_blocks=[5, 2, 3, 1, 2], cycle_days=12)
    with pytest.raises(ValueError):
        OptimizationCycle(cycle_blocks=[])


def test_priority_order_is_a_permutation():
    order = list(reversed(ProjectState().optimization_priorities))
    assert ProjectState(optimization_priorities=order).optimization_priorities == order
    with pytest.raises(ValueError):
        ProjectState(optimization_priorities=order[:-1])
    with pytest.raises(ValueError):
        ProjectState(optimization_priorities=["people_total"] * 6)


def existing_project():
    original = project(2)
    original.groups = [
        ScheduleGroup(
            id="a",
            name="Equipe A",
            shift_id="day",
            employee_count=1,
            work_days=1,
            rest_days=1,
            cycle_days=2,
            overrides={"2026-01-01": False},
            layer_by_shift={"day": 3},
        ),
        ScheduleGroup(
            id="b",
            name="Equipe B",
            shift_id="day",
            employee_count=1,
            work_days=1,
            rest_days=1,
            cycle_days=2,
            cycle_phase_offset=1,
        ),
    ]
    return original


def current_options(**kwargs):
    return OptimizationOptions(
        optimize_existing=True,
        cycles=[OptimizationCycle(cycle_blocks=[1, 1])],
        time_limit_seconds=5,
        max_solutions=2,
        max_group_size=4,
        max_employees=8,
        **kwargs,
    )


def test_existing_mode_resizes_preserving_groups_and_manual_settings():
    original = existing_project()
    before = EntityCodec.dump(original, mode="json")
    result = ScheduleOptimizer().optimize(original, current_options(change_cycles=False))
    assert result["metrics"]["deficit_staff_days"] == 2  # Manual day off is preserved.
    assert result["metrics"]["people_total"] == 4
    best = EntityCodec.load(ProjectState, result["project"])
    for old, new in zip(original.groups, best.groups):
        assert new.id == old.id and new.name == old.name
        assert new.allocations == {"day": 2}
        assert new.overrides == old.overrides and new.layer_by_shift == old.layer_by_shift
        assert new.blocks == old.blocks
        assert new.cycle_days == old.cycle_days
        assert new.work_hours_by_weekday == old.work_hours_by_weekday
    assert EntityCodec.dump(original, mode="json") == before
    assert result["solutions"][0]["group_changes"]


def test_priorities_change_solver_decision_and_ranking():
    original = existing_project()
    original.optimization_priorities.remove("people_total")
    original.optimization_priorities.insert(0, "people_total")
    result = ScheduleOptimizer().optimize(original, current_options(change_cycles=False))
    assert result["metrics"]["people_total"] == 0
    assert result["metrics"]["deficit_staff_days"] == 730
    assert result["priorities"] == original.optimization_priorities
    assert all(s["ranking"][0] == s["metrics"]["people_total"] for s in result["solutions"])
    assert result["stages"][0]["objective"] == "people_total"


def test_locked_sizes_and_declared_cycle_length_are_respected():
    original = existing_project()
    opts = current_options(change_employee_counts=False)
    opts.cycles = [OptimizationCycle(cycle_blocks=[2, 1, 3, 1])]
    result = ScheduleOptimizer().optimize(original, opts)
    for solution in result["solutions"]:
        for group in solution["project"]["groups"]:
            validated = EntityCodec.load(ScheduleGroup, group)
            assert validated.cycle_length == 2
            assert validated.allocations == {"day": 1}


def test_complement_optimizer_accepts_composite_patterns():
    original = project(1)
    result = ScheduleOptimizer().optimize(
        original,
        OptimizationOptions(
            cycles=[OptimizationCycle(cycle_blocks=[1, 1, 1, 1])],
            max_solutions=2,
            time_limit_seconds=5,
            max_group_size=1,
            max_employees=2,
            max_groups=2,
        ),
    )
    assert result["metrics"]["deficit_staff_days"] == 0
    assert all(g["cycle_blocks"] == [1, 1, 1, 1] for g in result["project"]["groups"])


def test_existing_optimizer_changes_cycle_and_phase_to_meet_rules():
    original = project(1)
    original.rules.max_consecutive_work_days = 1
    original.groups = [
        ScheduleGroup(id="g", name="G", shift_id="day", employee_count=1, work_days=5, rest_days=1)
    ]
    order = original.optimization_priorities
    order.remove("rule_violation_count")
    order.insert(0, "rule_violation_count")
    result = ScheduleOptimizer().optimize(original, current_options(change_employee_counts=False))
    assert result["metrics"]["rule_violation_count"] == 0
    assert EntityCodec.load(ScheduleGroup, result["project"]["groups"][0]).blocks == [1, 1]
    assert result["project"]["groups"][0]["id"] == "g"


def test_current_mode_composite_api_never_saves_proposals(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from escala_analyzer.container import ApplicationContainer
    from escala_analyzer.infrastructure.json_repository import JsonProjectRepository
    from escala_analyzer.presentation import local as main

    original = existing_project()
    original.groups[0].cycle_blocks = [1, 1, 1, 1]
    original.groups[0].cycle_days = 4
    repository = JsonProjectRepository(tmp_path / "project.json")
    repository.save(original)
    before = repository.path.read_bytes()
    monkeypatch.setattr(main, "container", ApplicationContainer(repository=repository))
    with TestClient(main.app) as client:
        response = client.post(
            "/api/optimize",
            json={
                "project": EntityCodec.dump(original, mode="json"),
                "options": EntityCodec.dump(current_options(), mode="json"),
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert any(not solution["baseline"] for solution in result["solutions"])
        for solution in result["solutions"]:
            assert len(EntityCodec.load(ProjectState, solution["project"]).groups) == 2
        assert repository.path.read_bytes() == before
        payload = EntityCodec.dump(original, mode="json")
        payload["groups"][0]["cycle_days"] = 9
        assert client.put("/api/project", json=payload).status_code == 422


def test_existing_rotating_team_remains_one_shared_team():
    original = project(1)
    original.shifts.append(replace(original.shifts[0], id="night", name="Noite"))
    original.groups = [
        ScheduleGroup(
            id="r",
            name="Rotativa",
            allocations={"day": 1, "night": 1},
            employee_count=1,
            rotation_shift_ids=["day", "night"],
            cycle_blocks=[1, 1, 1],
            cycle_days=3,
        )
    ]
    result = ScheduleOptimizer().optimize(original, current_options(change_cycles=False))
    for solution in result["solutions"]:
        group = EntityCodec.load(ProjectState, solution["project"]).groups[0]
        assert group.rotation_shift_ids == ["day", "night"]
        assert group.allocations["day"] == group.allocations["night"] == group.employee_count
        assert solution["metrics"]["people_total"] == group.employee_count
