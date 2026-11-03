from app.stock import from_scale, total_units


def test_truncates_fractional_reading():
    assert from_scale("A", 3.7).units == 3


def test_total():
    assert total_units([from_scale("A", 2.2), from_scale("B", 5.9)]) == 7
