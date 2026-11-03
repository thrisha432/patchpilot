from datetime import date

import pytest
from pydantic import ValidationError

from app.bookings import Booking


def test_end_from_nights():
    assert Booking(start="2024-01-01", nights=3).end == date(2024, 1, 4)


def test_nights_computed():
    assert Booking(start="2024-01-01", end="2024-01-06").nights == 5


def test_end_before_start():
    with pytest.raises(ValidationError):
        Booking(start="2024-01-05", end="2024-01-01")
