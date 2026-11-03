from app.service import audit_snapshot, duplicate, place, summary

RAW = {"id": "o1", "lines": [{"sku": "a", "qty": 2, "price": 1.25}, {"sku": "b", "qty": 1, "price": 3}]}


def test_total_and_summary():
    assert summary(place(RAW)) == {"id": "o1", "total": 5.5}


def test_duplicate_is_deep():
    order = place(RAW)
    clone = duplicate(order, "o2")
    clone.lines[0].qty = 99
    assert order.lines[0].qty == 2 and clone.id == "o2"
