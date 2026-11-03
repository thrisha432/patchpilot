from app.docs import endpoint_schema


def test_example_kept():
    assert endpoint_schema()["example"] == {"path": "/items", "methods": ["GET"]}


def test_required():
    assert set(endpoint_schema()["required"]) == {"path", "methods"}
