"""Primitive value contracts used throughout the domain."""

from __future__ import annotations

from typing import Literal

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]

OptimizationPriority = Literal[
    "deficit_staff_days",
    "deficit_work_hours",
    "rule_violation_count",
    "pattern_count",
    "monthly_staff_cost",
    "group_count",
    "surplus_staff_days",
    "people_total",
]

OPTIMIZATION_PRIORITIES: tuple[OptimizationPriority, ...] = (
    "deficit_staff_days",
    "deficit_work_hours",
    "rule_violation_count",
    "pattern_count",
    "monthly_staff_cost",
    "group_count",
    "surplus_staff_days",
    "people_total",
)
