from app.readings import Reading, parse_readings, parse_thresholds


def test_readings():
    rows = parse_readings([{"sensor": "t1", "value": "1.5"}])
    assert rows == [Reading(sensor="t1", value=1.5)]


def test_thresholds():
    assert parse_thresholds({"t1": "2"}) == {"t1": 2.0}
