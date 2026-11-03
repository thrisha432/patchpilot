from decimal import Decimal

from app.prices import PricePoint


def test_python_side_still_decimal():
    assert PricePoint(sku="A", price="1.10").price == Decimal("1.10")
