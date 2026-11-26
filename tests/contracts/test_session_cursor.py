import datetime

import pytest

from flightlog.contracts.sessions import SessionCursor

T0 = datetime.datetime(2026, 11, 20, 9, 0, 0, 123456, tzinfo=datetime.UTC)


def test_a_cursor_survives_the_round_trip_through_its_token():
    cursor = SessionCursor(T0, 42)

    assert SessionCursor.from_token(cursor.to_token()) == cursor


def test_the_token_is_safe_in_a_url():
    token = SessionCursor(T0, 42).to_token()

    assert all(c.isalnum() or c in "-_" for c in token)


@pytest.mark.parametrize("token", ["", "nonsense", "!!!", "MjAyNi0xMS0yMA", "eA"])
def test_a_token_this_class_did_not_make_is_rejected(token):
    with pytest.raises(ValueError):
        SessionCursor.from_token(token)


def test_a_token_with_a_naive_time_is_rejected():
    naive = SessionCursor(T0.replace(tzinfo=None), 42).to_token()

    with pytest.raises(ValueError):
        SessionCursor.from_token(naive)
