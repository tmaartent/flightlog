import datetime

import pytest

from flightlog.contracts.report import IsoWeek


def test_a_week_runs_from_monday_to_monday_in_utc():
    week = IsoWeek.parse("2026-W46")

    assert week.start == datetime.datetime(2026, 11, 9, tzinfo=datetime.UTC)
    assert week.end == datetime.datetime(2026, 11, 16, tzinfo=datetime.UTC)
    assert str(week) == "2026-W46"


def test_week_one_can_start_in_the_year_before():
    assert IsoWeek.parse("2026-W01").start == datetime.datetime(2025, 12, 29, tzinfo=datetime.UTC)


@pytest.mark.parametrize(
    "text", ["2026-46", "2026-W4", "26-W46", "2026-W46x", "2026-W00", "2026-W54"]
)
def test_anything_else_is_refused(text):
    with pytest.raises(ValueError):
        IsoWeek.parse(text)


def test_2026_has_53_weeks():
    assert str(IsoWeek.parse("2026-W53")) == "2026-W53"


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (datetime.date(2026, 11, 26), "2026-W47"),  # a Thursday in W48
        (datetime.date(2026, 11, 23), "2026-W47"),  # the Monday of W48
        (datetime.date(2027, 1, 6), "2026-W53"),  # across the new year
    ],
)
def test_the_last_full_week(today, expected):
    assert str(IsoWeek.last_full_week(today)) == expected
