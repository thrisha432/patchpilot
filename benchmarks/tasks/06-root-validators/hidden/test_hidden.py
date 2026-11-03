import pytest
from pydantic import ValidationError

from app.bookings import Booking


def test_same_day_rejected():
    with pytest.raises(ValidationError):
        Booking(start="2024-01-01", end="2024-01-01")


def test_explicit_nights_overridden_by_dates():
    assert Booking(start="2024-01-01", end="2024-01-03", nights=9).nights == 2
