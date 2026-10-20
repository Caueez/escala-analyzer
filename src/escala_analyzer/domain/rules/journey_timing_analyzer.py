"""JourneyTimingAnalyzer responsibility for schedule rule analysis."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.contracts.analysis_contracts import (
    AnalysisIssue,
)
from escala_analyzer.domain.entities import ProjectState, Shift


class JourneyTimingAnalyzer:
    def analyze(
        self,
        project: ProjectState,
        year_start: date,
        year_end: date,
        shifts: dict[str, Shift],
        issues: list[AnalysisIssue],
    ) -> None:
        for group in project.groups:
            # Without rotation each allocation represents a different fixed team.
            teams = [None] if group.rotation_shift_ids else list(group.allocations)
            for team in teams:
                previous_end = None
                reported: dict[tuple[str, int, str], AnalysisIssue] = {}
                day = year_start - timedelta(days=63)
                while day <= year_end:
                    if not ScheduleCalendar.is_working(group, day):
                        day += timedelta(days=1)
                        continue
                    sid = ScheduleCalendar.shift_on(group, day) if team is None else team
                    assert sid is not None
                    shift = ScheduleCalendar.effective_shift(group, shifts[sid], day)
                    rules = project.rules_on(day)
                    failures = []
                    minimum = 0
                    low = group.min_hours_by_weekday[day.weekday()]
                    high = group.max_hours_by_weekday[day.weekday()]
                    if (
                        group.allow_hours_optimization
                        and not low - 1e-9 <= shift.work_hours <= high + 1e-9
                    ):
                        failures.append(
                            (
                                "daily-hours-range",
                                f"{group.name}: {shift.work_hours:g} h efetivas em {day.isoformat()}; limites do grupo: {low:g} a {high:g} h.",
                            )
                        )
                    if rules.check_breaks:
                        minimum = (
                            rules.min_break_over_6h_minutes
                            if shift.work_hours > 6
                            else rules.min_break_over_4h_minutes
                            if shift.work_hours > 4
                            else 0
                        )
                        if shift.break_minutes < minimum:
                            failures.append(
                                (
                                    "intrajornada",
                                    (
                                        f"{shift.name}: pausa de {shift.break_minutes} min; mínimo configurado de {minimum} min. "
                                        "Ajuste a pausa em Configurações → Demanda por turno, ou o mínimo em "
                                        "Horários e intervalos. Desativar a validação do mínimo não desativa o cálculo das horas."
                                    ),
                                )
                            )
                    if shift.start_time is None:
                        if rules.check_intershift_rest:
                            failures.append(
                                (
                                    "missing-shift-time",
                                    "Informe o horário de início para verificar o descanso entre jornadas.",
                                )
                            )
                        previous_end = None
                    else:
                        start = datetime.combine(day, shift.start_time)
                        if rules.check_intershift_rest and previous_end is not None:
                            hours = (start - previous_end).total_seconds() / 3600
                            if hours < rules.min_intershift_hours:
                                failures.append(
                                    (
                                        "interjornada",
                                        f"{hours:g} h entre jornadas; mínimo {rules.min_intershift_hours:g} h.",
                                    )
                                )
                        previous_end = start + timedelta(hours=shift.elapsed_hours)
                    for code, message in failures:
                        key = (code, day.month, sid)
                        if day >= year_start and key in reported:
                            reported[key]["occurrences_count"] = (
                                reported[key].get("occurrences_count", 0) + 1
                            )
                            reported[key]["last_date"] = day.isoformat()
                        elif day >= year_start:
                            record: AnalysisIssue = {
                                "code": code,
                                "severity": "rule",
                                "month": day.month,
                                "group_id": group.id,
                                "group_name": group.name,
                                "shift_id": sid,
                                "shift_name": shift.name,
                                "occurrences_count": 1,
                                "last_date": day.isoformat(),
                                "date": day.isoformat(),
                                "title": "Jornada diária fora dos limites do grupo"
                                if code == "daily-hours-range"
                                else "Pausa abaixo do mínimo configurado"
                                if code == "intrajornada"
                                else "Parâmetro de descanso entre jornadas não atendido",
                                "configuration_section": "groupHoursRows"
                                if code == "daily-hours-range"
                                else "timingRules",
                                "actual": shift.break_minutes if code == "intrajornada" else None,
                                "expected": minimum if code == "intrajornada" else None,
                                "message": message,
                            }
                            reported[key] = record
                            issues.append(record)
                    day += timedelta(days=1)
