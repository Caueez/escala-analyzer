"""Validate external payloads and map between schemas and pure domain dataclasses."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import date, time
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from escala_analyzer.domain import entities
from escala_analyzer.domain.optimization import optimization_options
from escala_analyzer.infrastructure.schemas import optimization, project

T = TypeVar("T")


class EntityCodec:
    @staticmethod
    def load(entity_type: type[T], payload: object) -> T:
        schema_type = getattr(project, entity_type.__name__, None) or getattr(
            optimization, entity_type.__name__
        )
        return cast(T, EntityCodec.to_domain(schema_type.model_validate(payload)))

    @staticmethod
    def to_domain(value: Any) -> Any:
        if isinstance(value, BaseModel):
            cls = getattr(entities, type(value).__name__, None) or getattr(
                optimization_options, type(value).__name__
            )
            data = {
                key: EntityCodec.to_domain(getattr(value, key)) for key in type(value).model_fields
            }
            if (
                type(value).__name__ == "OptimizationOptions"
                and "cycles" in value.model_fields_set
                and "automatic_cycles" not in value.model_fields_set
            ):
                data["automatic_cycles"] = False
            return cls(**data)
        if isinstance(value, list):
            return [EntityCodec.to_domain(item) for item in value]
        if isinstance(value, dict):
            return {key: EntityCodec.to_domain(item) for key, item in value.items()}
        return value

    @staticmethod
    def dump(value: object, mode: str = "python") -> dict[str, Any]:
        if not is_dataclass(value) or isinstance(value, type):
            raise TypeError("Expected a domain dataclass instance.")
        return {
            item.name: EntityCodec.encode(getattr(value, item.name), mode) for item in fields(value)
        }

    @staticmethod
    def encode(value: Any, mode: str) -> Any:
        if is_dataclass(value) and not isinstance(value, type):
            return EntityCodec.dump(value, mode)
        if isinstance(value, (date, time)):
            return value.isoformat() if mode == "json" else value
        if isinstance(value, dict):
            return {key: EntityCodec.encode(item, mode) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            items = [EntityCodec.encode(item, mode) for item in value]
            return set(items) if isinstance(value, set) and mode != "json" else items
        return value

    @staticmethod
    def dump_json(value: object) -> str:
        return json.dumps(EntityCodec.dump(value, mode="json"), ensure_ascii=False)
