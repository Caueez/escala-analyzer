"""Guard the domain boundary independently from installed frameworks."""

from __future__ import annotations

import ast
import subprocess
import sys
from dataclasses import is_dataclass, replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from escala_analyzer.domain.contracts.optimization_contracts import CandidatePattern
from escala_analyzer.domain.entities import (
    BusinessConstraints,
    CompanySettings,
    ProjectState,
    RulePeriod,
    RuleSettings,
    ScheduleGroup,
    Shift,
)
from escala_analyzer.domain.optimization.optimization_options import (
    OptimizationCycle,
    OptimizationOptions,
)
from escala_analyzer.infrastructure.serialization.entity_codec import EntityCodec

SOURCE = Path(__file__).resolve().parents[1] / "src"
DOMAIN = SOURCE / "escala_analyzer/domain"


def test_domain_imports_only_itself_and_the_standard_library() -> None:
    for path in DOMAIN.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                assert (
                    module.split(".")[0] in sys.stdlib_module_names
                    or module == "escala_analyzer.domain"
                    or module.startswith("escala_analyzer.domain.")
                ), (path, module)


def test_domain_can_be_loaded_without_site_packages() -> None:
    script = f"""
import sys, pkgutil, importlib
sys.path.insert(0, {str(SOURCE)!r})
import escala_analyzer.domain
for module in pkgutil.walk_packages(escala_analyzer.domain.__path__, 'escala_analyzer.domain.'):
    importlib.import_module(module.name)
assert not any(name in sys.modules for name in ('pydantic', 'ortools', 'fastapi'))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_domain_does_not_access_private_members_of_other_objects() -> None:
    for path in DOMAIN.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Attribute) or not node.attr.startswith("_"):
                continue
            if node.attr.startswith("__") and node.attr.endswith("__"):
                continue
            assert isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"}, (
                path,
                node.lineno,
            )


def test_domain_entities_and_search_values_are_dataclasses() -> None:
    for cls in (
        Shift,
        ScheduleGroup,
        ProjectState,
        RuleSettings,
        RulePeriod,
        CompanySettings,
        BusinessConstraints,
        OptimizationCycle,
        OptimizationOptions,
        CandidatePattern,
    ):
        assert is_dataclass(cls), cls
    first = ProjectState()
    second = ProjectState()
    first.shifts.append(Shift(id="day", name="Dia"))
    assert not second.shifts
    assert not hasattr(first, "model_dump")
    assert not hasattr(first, "model_validate")


def test_dataclass_replacement_preserves_business_invariants() -> None:
    group = ScheduleGroup(id="g", name="G", cycle_blocks=[3, 1], cycle_days=4)
    with pytest.raises(ValueError, match="soma"):
        replace(group, cycle_blocks=[2, 1])
    with pytest.raises(ValueError):
        BusinessConstraints(monthly_budget=100, monthly_employee_cost=0)


def test_json_boundary_migrates_and_round_trips_pure_entities() -> None:
    project = EntityCodec.load(
        ProjectState,
        {
            "name": "Legado",
            "planning": {},
            "shifts": [{"id": "day", "name": "Dia", "journey_id": "old", "start_time": "08:00"}],
            "groups": [{"id": "g", "name": "G", "shift_id": "day", "employee_count": 2}],
        },
    )
    assert is_dataclass(project.shifts[0])
    assert project.groups[0].allocations == {"day": 2}
    payload = EntityCodec.dump(project, mode="json")
    assert "planning" not in payload
    assert EntityCodec.load(ProjectState, payload) == project
    with pytest.raises(ValidationError):
        EntityCodec.load(ProjectState, {"unexpected_field": True})


def test_json_boundary_keeps_explicit_cycle_selection() -> None:
    options = EntityCodec.load(OptimizationOptions, {"cycles": [{"work_days": 2, "rest_days": 1}]})
    assert [cycle.blocks for cycle in options.candidate_cycles()] == [[2, 1]]
    automatic = EntityCodec.load(
        OptimizationOptions,
        {
            "automatic_cycles": True,
            "max_cycle_days": 3,
            "cycles": [{"work_days": 2, "rest_days": 1}],
        },
    )
    assert len(automatic.candidate_cycles()) > 1
