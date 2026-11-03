import pytest

from app.geo import make_point


def test_point():
    p = make_point("  oslo ", "59.91", 10.75)
    assert (p.label, p.lat, p.lon) == ("Oslo", 59.91, 10.75)


def test_out_of_range():
    with pytest.raises(ValueError):
        make_point("x", 91, 0)
