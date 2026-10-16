"""Projeto inicial demonstrativo; todos os números podem ser alterados na interface."""

from __future__ import annotations

from datetime import date, timedelta

from .models import ProjectState, RuleSettings, ScheduleGroup, Shift

WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def create_default_project() -> ProjectState:
    shifts = [
        Shift(id="turno-1", name="1º turno · manhã", hours_per_day=8.0, demand_by_weekday=[45] * 7),
        Shift(id="turno-2", name="2º turno · tarde", hours_per_day=8.0, demand_by_weekday=[45] * 7),
        Shift(id="turno-3", name="3º turno · noite", hours_per_day=8.0, demand_by_weekday=[35] * 7),
    ]

    # Hipótese inicial descrita na conversa: 101 pessoas no 3x1, com 36/34/31 por turno.
    # Cinco grupos por turno são apenas uma demonstração, não uma afirmação sobre a fábrica.
    distributions = {
        "turno-1": [8, 7, 7, 7, 7],  # 36
        "turno-2": [7, 7, 7, 7, 6],  # 34
        "turno-3": [7, 6, 6, 6, 6],  # 31
    }
    groups: list[ScheduleGroup] = []
    for shift_index, shift in enumerate(shifts):
        for group_index, count in enumerate(distributions[shift.id]):
            # Fases diferentes tornam o exemplo visualmente útil. Cada âncora é editável.
            anchor = date(2027, 1, 1) + timedelta(days=(group_index + shift_index * 2) % 4)
            letter = chr(ord("A") + group_index)
            groups.append(
                ScheduleGroup(
                    id=f"{shift.id}-grupo-{letter.lower()}",
                    name=f"Grupo {letter}",
                    shift_id=shift.id,
                    employee_count=count,
                    work_days=3,
                    rest_days=1,
                    cycle_anchor=anchor,
                )
            )

    return ProjectState(
        name="Fiação — modelo inicial editável",
        year=2027,
        selected_month=1,
        shifts=shifts,
        groups=groups,
        rules=RuleSettings(),
        notes=(
            "MODELO DEMONSTRATIVO: 101 pessoas distribuídas provisoriamente em 36/34/31 por turno, "
            "com cinco grupos por turno, ciclo 3x1 e demanda ilustrativa de 45/45/35. "
            "Nada disso substitui a planilha e os parâmetros reais da empresa."
        ),
    )
