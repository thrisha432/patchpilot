from app.pipeline import parse_all, roundtrip, to_sink


def test_parse_and_roundtrip():
    rows = [{"kind": "a", "seq": "1"}, {"kind": "b", "seq": 2}]
    assert [e.seq for e in parse_all(rows)] == [1, 2]
    assert roundtrip(rows) == [{"kind": "a", "seq": 1}, {"kind": "b", "seq": 2}]


def test_sink():
    assert to_sink(parse_all([{"kind": "x", "seq": 5}])[0], "dict") == {"kind": "x", "seq": 5}
