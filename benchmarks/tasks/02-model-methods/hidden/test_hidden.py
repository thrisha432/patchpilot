from app.service import load_order, load_order_json, to_json, with_note

PAYLOAD = {"id": "o-2", "customer": "bob", "items": []}


def test_parse_raw_round_trip():
    order = load_order(PAYLOAD)
    assert load_order_json(to_json(order)) == order


def test_copy_does_not_mutate():
    order = load_order(PAYLOAD)
    with_note(order, "x")
    assert order.note is None
