"""GroupPeriodReporter responsibility for schedule rule analysis."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.contracts.analysis_contracts import (
    AllocationDetails,
    GroupPeriodDetails,
    Journey,
)
from escala_analyzer.domain.entities import ScheduleGroup, Shift


class GroupPeriodReporter:
    def report(
        self, group: ScheduleGroup, shifts: dict[str, Shift], days: list[date]
    ) -> GroupPeriodDetails:
        off = [day for day in days if not ScheduleCalendar.is_working(group, day)]
        allocations: list[AllocationDetails] = []
        for team in [None] if group.rotation_shift_ids else list(group.allocations):
            journeys: list[Journey] = []
            rests: list[float] = []
            work_hours = break_hours = 0.0
            complete = True
            previous_end = None
            day = days[0] - timedelta(days=63)
            while day <= days[-1]:
                if ScheduleCalendar.is_working(group, day):
                    sid = ScheduleCalendar.shift_on(group, day) if team is None else team
                    assert sid is not None
                    shift = ScheduleCalendar.effective_shift(group, shifts[sid], day)
                    start = datetime.combine(day, shift.start_time) if shift.start_time else None
                    end = start + timedelta(hours=shift.elapsed_hours) if start else None
                    rest = (
                        (start - previous_end).total_seconds() / 3600
                        if start and previous_end
                        else None
                    )
                    if day >= days[0]:
                        work_hours += shift.work_hours
                        break_hours += shift.break_minutes / 60
                        complete = complete and start is not None
                        if rest is not None:
                            rests.append(rest)
                        journeys.append(
                            {
                                "date": day.isoformat(),
                                "shift_id": sid,
                                "shift_name": shift.name,
                                "start": start.isoformat() if start else None,
                                "end": end.isoformat() if end else None,
                                "work_hours": shift.work_hours,
                                "break_minutes": shift.break_minutes,
                                "rest_before_hours": rest,
                            }
                        )
                    previous_end = end
                day += timedelta(days=1)
            allocations.append(
                {
                    "shift_id": team,
                    "shift_name": shifts[team].name if team else "Revezamento",
                    "employees": group.allocations[team] if team else group.employee_count,
                    "work_days": len(journeys),
                    "work_hours": round(work_hours, 4),
                    "break_hours": round(break_hours, 4),
                    "rest_hours": round(len(days) * 24 - work_hours - break_hours, 4),
                    "min_intershift_hours": min(rests) if rests else None,
                    "max_intershift_hours": max(rests) if rests else None,
                    "timing_complete": complete,
                    "journeys": journeys,
                }
            )
        result: GroupPeriodDetails = {
            "group_id": group.id,
            "group_name": group.name,
            "days_off": len(off),
            "days_off_by_weekday": [sum(d.weekday() == i for d in off) for i in range(7)],
            "sundays_off": sum(d.weekday() == 6 for d in off),
            "hours_basis": "Horas por pessoa, atribuídas à data de início da jornada. Descanso total é o saldo de horas do período, descontando trabalho e intervalos. O resumo do grupo usa a equipe com maior carga; veja as alocações para cada equipe.",
            "allocations": allocations,
        }
        if allocations:
            representative = max(allocations, key=lambda item: item.get("work_hours", 0))
            result["work_days"] = representative.get("work_days", 0)
            result["work_hours"] = representative.get("work_hours", 0)
            result["break_hours"] = representative.get("break_hours", 0)
            result["rest_hours"] = representative.get("rest_hours", 0)
            result["min_intershift_hours"] = representative.get("min_intershift_hours")
            result["max_intershift_hours"] = representative.get("max_intershift_hours")
            result["timing_complete"] = representative.get("timing_complete", False)
        return result
