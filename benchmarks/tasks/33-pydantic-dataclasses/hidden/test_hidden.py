import pytest
from pydantic import ValidationError

from app.geo import make_point


def test_assignment_validated():
    p = make_point("a", 1, 2)
    with pytest.raises(ValidationError):
        p.lat = "north"
