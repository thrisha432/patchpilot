import json
from decimal import Decimal

from app.prices import PriceList, PricePoint, price_list_json


def test_prices_are_json_numbers():
    pl = PriceList(currency="EUR", points=[PricePoint(sku="A", price=Decimal("9.90"))])
    body = json.loads(price_list_json(pl))
    assert body == {"currency": "EUR", "points": [{"sku": "A", "price": 9.9, "discount": 0}]}
