from decimal import Decimal
from typing import List

from pydantic import BaseModel


class PricePoint(BaseModel):
    sku: str
    price: Decimal
    discount: Decimal = Decimal("0")


class PriceList(BaseModel):
    currency: str
    points: List[PricePoint]


def price_list_json(pl: PriceList) -> str:
    return pl.json()
