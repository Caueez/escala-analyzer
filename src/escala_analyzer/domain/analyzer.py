"""Motor determinístico para expandir ciclos e verificar regras configuradas."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from .models import ProjectState, ScheduleGroup, Shift


PT_MONTHS = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]
PT_WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


def is_working(group: ScheduleGroup, day: date) -> bool:
    """Retorna o estado efetivo no dia, respeitando ajustes manuais."""
    override = group.overrides.get(day.isoformat())
    if override is not None:
        return override
    cycle_length = group.work_days + group.rest_days
    cycle_position = (day - group.cycle_anchor).days % cycle_length
    return cycle_position < group.work_days


def _month_dates(year: int, month: int) -> list[date]:
    first = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return [first + timedelta(days=offset) for offset in range((next_month - first).days)]


def _as_shift_lookup(shifts: list[Shift]) -> dict[str, Shift]:
    return {shift.id: shift for shift in shifts}


def analyze_project(project: ProjectState) -> dict[str, Any]:
    """Analisa cobertura e parâmetros por todos os dias do ano selecionado.

    Os achados descrevem o cenário configurado no projeto. Eles não são um laudo
    de conformidade jurídica e não substituem a conferência de convenção coletiva.
    """
    year_start = date(project.year, 1, 1)
    year_end = date(project.year, 12, 31)
    calendar_dates = [year_start + timedelta(days=i) for i in range((year_end - year_start).days + 1)]
    shifts = _as_shift_lookup(project.shifts)
    groups_by_shift: dict[str, list[ScheduleGroup]] = defaultdict(list)
    for group in project.groups:
        groups_by_shift[group.shift_id].append(group)

    coverage_by_day: list[dict[str, Any]] = []
    coverage_issues: list[dict[str, Any]] = []
    monthly_coverage_counts: dict[int, int] = defaultdict(int)
    monthly_peak_deficit: dict[int, int] = defaultdict(int)
    monthly_max_shortage_by_shift: dict[tuple[int, str], int] = defaultdict(int)
    monthly_required: dict[tuple[int, str], int] = defaultdict(int)
    monthly_scheduled: dict[tuple[int, str], int] = defaultdict(int)

    for day in calendar_dates:
        day_shifts: list[dict[str, Any]] = []
        total_required = 0
        total_scheduled = 0
        total_deficit = 0
        for shift in project.shifts:
            scheduled = sum(
                group.employee_count
                for group in groups_by_shift.get(shift.id, [])
                if is_working(group, day)
            )
            required = shift.demand_by_weekday[day.weekday()]
            deficit = max(0, required - scheduled)
            surplus = max(0, scheduled - required)
            item = {
                "shift_id": shift.id,
                "shift_name": shift.name,
                "required": required,
                "scheduled": scheduled,
                "deficit": deficit,
                "surplus": surplus,
            }
            day_shifts.append(item)
            total_required += required
            total_scheduled += scheduled
            total_deficit += deficit
            monthly_required[(day.month, shift.id)] += required
            monthly_scheduled[(day.month, shift.id)] += scheduled
            monthly_max_shortage_by_shift[(day.month, shift.id)] = max(
                monthly_max_shortage_by_shift[(day.month, shift.id)], deficit
            )
            if deficit:
                monthly_coverage_counts[day.month] += 1
                monthly_peak_deficit[day.month] = max(monthly_peak_deficit[day.month], deficit)
                coverage_issues.append(
                    {
                        "code": "coverage-gap",
                        "severity": "operational",
                        "date": day.isoformat(),
                        "month": day.month,
                        "title": "Cobertura abaixo da demanda",
                        "message": (
                            f"{shift.name}: faltam {deficit} pessoa(s); "
                            f"demanda {required}, escala {scheduled}."
                        ),
                        **item,
                    }
                )
        coverage_by_day.append(
            {
                "date": day.isoformat(),
                "weekday": day.weekday(),
                "day": day.day,
                "month": day.month,
                "is_sunday": day.weekday() == 6,
                "total_required": total_required,
                "total_scheduled": total_scheduled,
                "total_deficit": total_deficit,
                "shifts": day_shifts,
            }
        )

    # Parâmetros por grupo e por mês: descanso total e domingos de descanso.
    group_monthly: list[dict[str, Any]] = []
    rule_issues: list[dict[str, Any]] = []
    for group in project.groups:
        shift = shifts[group.shift_id]
        for month in range(1, 13):
            month_days = _month_dates(project.year, month)
            off_days = [day for day in month_days if not is_working(group, day)]
            sunday_offs = [day for day in off_days if day.weekday() == 6]
            monthly_item = {
                "group_id": group.id,
                "group_name": group.name,
                "shift_id": group.shift_id,
                "shift_name": shift.name,
                "month": month,
                "month_name": PT_MONTHS[month - 1],
                "employees": group.employee_count,
                "days_off": len(off_days),
                "sundays_off": len(sunday_offs),
                "sunday_dates_off": [day.isoformat() for day in sunday_offs],
            }
            group_monthly.append(monthly_item)

            if project.rules.check_min_days_off_per_month and len(off_days) < project.rules.min_days_off_per_month:
                rule_issues.append(
                    {
                        "code": "monthly-rest-days",
                        "severity": "rule",
                        "month": month,
                        "group_id": group.id,
                        "group_name": group.name,
                        "shift_name": shift.name,
                        "title": "Descansos mensais abaixo do parâmetro",
                        "message": (
                            f"{group.name} ({shift.name}) tem {len(off_days)} dia(s) de folga em "
                            f"{PT_MONTHS[month - 1]}; o parâmetro configurado é "
                            f"{project.rules.min_days_off_per_month}."
                        ),
                        "actual": len(off_days),
                        "expected": project.rules.min_days_off_per_month,
                    }
                )

            if len(sunday_offs) < project.rules.min_sundays_off_per_month:
                rule_issues.append(
                    {
                        "code": "monthly-sunday-rest",
                        "severity": "rule",
                        "month": month,
                        "group_id": group.id,
                        "group_name": group.name,
                        "shift_name": shift.name,
                        "title": "Domingos de folga abaixo do parâmetro",
                        "message": (
                            f"{group.name} ({shift.name}) tem {len(sunday_offs)} domingo(s) de folga em "
                            f"{PT_MONTHS[month - 1]}; o parâmetro configurado é "
                            f"{project.rules.min_sundays_off_per_month}."
                        ),
                        "actual": len(sunday_offs),
                        "expected": project.rules.min_sundays_off_per_month,
                    }
                )

    # Janelas móveis de 7 dias: iniciamos antes do ano para avaliar janelas que
    # atravessam 1 de janeiro, e continuamos até 31 de dezembro.
    window_start = year_start - timedelta(days=6)
    window_end = year_end
    window_issue_counts: dict[tuple[str, str, int], dict[str, Any]] = {}
    for group in project.groups:
        shift = shifts[group.shift_id]
        day = window_start
        while day <= window_end:
            window = [day + timedelta(days=offset) for offset in range(7)]
            if not any(year_start <= item <= year_end for item in window):
                day += timedelta(days=1)
                continue
            working_days = [item for item in window if is_working(group, item)]
            rest_count = 7 - len(working_days)
            weekly_hours = len(working_days) * shift.hours_per_day
            applicable_month = min(max(day.month, 1), 12)
            if day < year_start:
                applicable_month = 1
            window_end_date = window[-1]

            failures: list[tuple[str, str]] = []
            if rest_count < project.rules.min_rest_days_in_rolling_7:
                failures.append(
                    (
                        "rolling-rest",
                        f"{rest_count} dia(s) de descanso em uma janela de 7 dias; "
                        f"parâmetro: {project.rules.min_rest_days_in_rolling_7}.",
                    )
                )
            if weekly_hours > project.rules.weekly_max_hours + 1e-9:
                failures.append(
                    (
                        "rolling-hours",
                        f"{weekly_hours:g} h em uma janela de 7 dias; "
                        f"limite configurado: {project.rules.weekly_max_hours:g} h.",
                    )
                )

            # Registra cada mês que é tocado pela janela; agrupa os achados por grupo/regra/mês.
            touched_months = sorted({item.month for item in window if year_start <= item <= year_end})
            for code, detail in failures:
                for month in touched_months:
                    key = (group.id, code, month)
                    record = window_issue_counts.get(key)
                    if record is None:
                        record = {
                            "code": code,
                            "severity": "rule",
                            "month": month,
                            "group_id": group.id,
                            "group_name": group.name,
                            "shift_name": shift.name,
                            "title": (
                                "Descanso insuficiente em janela móvel de 7 dias"
                                if code == "rolling-rest"
                                else "Jornada semanal acima do parâmetro"
                            ),
                            "message": detail,
                            "windows_count": 0,
                            "first_window_start": day.isoformat(),
                            "last_window_start": day.isoformat(),
                        }
                        window_issue_counts[key] = record
                    record["windows_count"] += 1
                    record["last_window_start"] = day.isoformat()
            day += timedelta(days=1)

    for item in window_issue_counts.values():
        item["message"] = (
            f"{item['message']} Ocorrências em {PT_MONTHS[item['month'] - 1]}: "
            f"{item['windows_count']} janela(s); primeira janela iniciada em "
            f"{item['first_window_start']}."
        )
        rule_issues.append(item)

    # Sequências longas de trabalho, incluindo o contexto anterior a 1 de janeiro.
    for group in project.groups:
        shift = shifts[group.shift_id]
        scan_start = year_start - timedelta(days=31)
        scan_end = year_end
        streak_start: date | None = None
        streak_length = 0
        day = scan_start
        while day <= scan_end + timedelta(days=1):
            working = day <= scan_end and is_working(group, day)
            if working:
                if streak_length == 0:
                    streak_start = day
                streak_length += 1
            else:
                if streak_length > project.rules.max_consecutive_work_days and streak_start is not None:
                    first_over_limit = streak_start + timedelta(days=project.rules.max_consecutive_work_days)
                    if first_over_limit <= year_end and day >= year_start:
                        month = max(1, min(12, first_over_limit.month))
                        rule_issues.append(
                            {
                                "code": "consecutive-work",
                                "severity": "rule",
                                "month": month,
                                "group_id": group.id,
                                "group_name": group.name,
                                "shift_name": shift.name,
                                "title": "Sequência de trabalho acima do parâmetro",
                                "message": (
                                    f"{group.name} ({shift.name}) trabalhou {streak_length} dias seguidos; "
                                    f"o máximo configurado é {project.rules.max_consecutive_work_days}."
                                ),
                                "actual": streak_length,
                                "expected": project.rules.max_consecutive_work_days,
                                "date": first_over_limit.isoformat(),
                            }
                        )
                streak_start = None
                streak_length = 0
            day += timedelta(days=1)

    monthly_summary: list[dict[str, Any]] = []
    for month in range(1, 13):
        shift_rows = []
        for shift in project.shifts:
            shift_rows.append(
                {
                    "shift_id": shift.id,
                    "shift_name": shift.name,
                    "required_staff_days": monthly_required[(month, shift.id)],
                    "scheduled_staff_days": monthly_scheduled[(month, shift.id)],
                    "max_daily_deficit": monthly_max_shortage_by_shift[(month, shift.id)],
                }
            )
        monthly_summary.append(
            {
                "month": month,
                "month_name": PT_MONTHS[month - 1],
                "coverage_gap_count": monthly_coverage_counts[month],
                "worst_single_shift_deficit": monthly_peak_deficit[month],
                "shifts": shift_rows,
            }
        )

    # O painel recebe todos os déficits e problemas de regra, mas pode exibir só os primeiros.
    issues = coverage_issues + rule_issues
    months_with_issues = sorted({issue.get("month") for issue in issues if issue.get("month")})
    return {
        "year": project.year,
        "days_in_year": len(calendar_dates),
        "people_total": sum(group.employee_count for group in project.groups),
        "group_count": len(project.groups),
        "shift_count": len(project.shifts),
        "coverage_gap_count": len(coverage_issues),
        "days_with_any_coverage_gap": len({item["date"] for item in coverage_issues}),
        "peak_single_shift_deficit": max((item["deficit"] for item in coverage_issues), default=0),
        "rule_issue_count": len(rule_issues),
        "months_with_issues": months_with_issues,
        "rules": project.rules.model_dump(mode="json"),
        "coverage_by_day": coverage_by_day,
        "coverage_issues": coverage_issues,
        "group_monthly": group_monthly,
        "monthly_summary": monthly_summary,
        "rule_issues": rule_issues,
        "issues": issues,
        "is_legal_opinion": False,
        "disclaimer": (
            "A análise verifica somente os parâmetros configurados no projeto. "
            "Ela não substitui legislação consolidada, convenção/acordo coletivo, "
            "regras específicas da categoria nem validação profissional."
        ),
    }
