import pytest
from pydantic import ValidationError

from app.readings import parse_readings, parse_thresholds


def test_invalid_reading():
    with pytest.raises(ValidationError):
        parse_readings([{"sensor": "t1", "value": "hot"}])


def test_invalid_threshold():
    with pytest.raises(ValidationError):
        parse_thresholds({"t1": "cold"})
