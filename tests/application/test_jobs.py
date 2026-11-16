from flightlog.application.jobs import BASE_DELAY, retry_delay


def test_retry_delay_gets_exponentially_longer_until_max_is_reached() -> None:
    delay = retry_delay(1)

    assert delay == BASE_DELAY

    delay = retry_delay(2)
    assert delay == BASE_DELAY * (2**1)

    delay = retry_delay(3)
    assert delay == BASE_DELAY * (2**2)

    delay = retry_delay(4)
    assert delay == BASE_DELAY * (2**3)

    delay = retry_delay(5)
    assert delay == BASE_DELAY * (2**4)

    delay = retry_delay(6)
    assert delay is None
