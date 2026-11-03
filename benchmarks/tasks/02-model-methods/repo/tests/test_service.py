import json

from app.service import load_order, order_total, public_view, to_json, with_note

PAYLOAD = {
    "id": "o-1",
    "customer": "ada",
    "items": [{"sku": "A", "quantity": 2, "unit_price": 1.25}],
    "note": "gift",
}


def test_load_and_total():
    assert order_total(load_order(PAYLOAD)) == 2.5


def test_public_view_hides_note():
    view = public_view(load_order(PAYLOAD))
    assert view == {"id": "o-1", "customer": "ada", "items": [{"sku": "A", "quantity": 2, "unit_price": 1.25}]}


def test_json_round_trip():
    assert json.loads(to_json(load_order(PAYLOAD)))["items"][0]["sku"] == "A"


def test_with_note():
    assert with_note(load_order(PAYLOAD), "rush").note == "rush"
