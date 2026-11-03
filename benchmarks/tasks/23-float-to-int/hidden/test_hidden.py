from app.stock import from_scale


def test_whole_reading():
    assert from_scale("C", 4.0).units == 4
