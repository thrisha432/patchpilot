from app.export import header, to_csv, trusted_rows


def test_header():
    assert header() == ["name", "qty", "price"]


def test_csv():
    rows = trusted_rows([{"name": "pen", "qty": 2, "price": 1.5}])
    assert to_csv(rows) == "name,qty,price\npen,2,1.5\n"
