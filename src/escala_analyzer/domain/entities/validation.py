"""Common numeric invariants of scheduling entities."""

from collections.abc import Sized
from math import isfinite


class DomainValidation:
    @staticmethod
    def range(name: str, value: float | None, minimum: float | None, maximum: float | None) -> None:
        if value is None:
            return
        if (
            not isfinite(value)
            or (minimum is not None and value < minimum)
            or (maximum is not None and value > maximum)
        ):
            raise ValueError(f"{name}: valor fora dos limites permitidos.")

    @staticmethod
    def length(name: str, value: Sized, minimum: int) -> None:
        if len(value) < minimum:
            raise ValueError(f"{name}: informe ao menos {minimum} item(ns).")
