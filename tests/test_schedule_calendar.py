from datetime import date

from escala_analyzer.domain.calendar.schedule_calendar import ScheduleCalendar
from escala_analyzer.domain.entities import ScheduleGroup


def make_group(
    work_days: int = 5,
    rest_days: int = 2,
    cycle_anchor: date = date(2026, 1, 1),
    overrides: dict[str, bool] | None = None,
) -> ScheduleGroup:
    return ScheduleGroup(
        id="group-1",
        name="Grupo A",
        shift_id="shift-1",
        employee_count=5,
        work_days=work_days,
        rest_days=rest_days,
        cycle_anchor=cycle_anchor,
        overrides=overrides or {},
    )


def test_cycle_marks_working_days() -> None:
    group = make_group()

    assert ScheduleCalendar.is_working(group, date(2026, 1, 1))
    assert ScheduleCalendar.is_working(group, date(2026, 1, 5))
    assert not ScheduleCalendar.is_working(group, date(2026, 1, 6))


def test_cycle_handles_dates_before_anchor() -> None:
    group = make_group()

    assert not ScheduleCalendar.is_working(
        group,
        date(2025, 12, 31),
    )


def test_cycle_handles_working_day_before_anchor() -> None:
    group = make_group()

    assert ScheduleCalendar.is_working(
        group,
        date(2025, 12, 29),
    )


def test_weekday_anchor_keeps_three_by_one_phase_across_weeks() -> None:
    group = make_group(work_days=3, rest_days=1)
    group.cycle_anchor_weekday = 0  # segunda-feira

    # 2024-01-01 é a referência de segunda: três dias de trabalho, um de folga.
    assert [ScheduleCalendar.is_working(group, date(2024, 1, day)) for day in range(1, 9)] == [
        True,
        True,
        True,
        False,
        True,
        True,
        True,
        False,
    ]


def test_override_takes_precedence_over_cycle() -> None:
    group = make_group(
        overrides={
            "2026-01-01": False,
            "2026-01-06": True,
        }
    )

    assert not ScheduleCalendar.is_working(group, date(2026, 1, 1))
    assert ScheduleCalendar.is_working(group, date(2026, 1, 6))


def test_february_2026_has_28_days() -> None:
    dates = ScheduleCalendar.month_dates(2026, 2)

    assert len(dates) == 28
    assert dates[0] == date(2026, 2, 1)
    assert dates[-1] == date(2026, 2, 28)


def test_february_leap_year_has_29_days() -> None:
    dates = ScheduleCalendar.month_dates(2028, 2)

    assert len(dates) == 29
    assert dates[-1] == date(2028, 2, 29)


def test_year_calendar_respects_leap_year() -> None:
    assert len(ScheduleCalendar.year_dates(2028)) == 366
    assert len(ScheduleCalendar.year_dates(2027)) == 365
