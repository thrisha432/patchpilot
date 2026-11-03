from app.pipeline import parse_all


def test_empty():
    assert parse_all([]) == []
