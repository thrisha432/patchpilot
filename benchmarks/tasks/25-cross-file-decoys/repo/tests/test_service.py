from app.service import export_order


def test_export_order():
    assert export_order({"id": 1, "items": ["a"], "total": "9.5"}) == {"id": 1, "items": ["a"], "total": 9.5}
