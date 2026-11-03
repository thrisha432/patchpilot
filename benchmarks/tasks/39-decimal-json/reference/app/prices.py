from decimal import Decimal
from typing import List

from pydantic import BaseModel, field_serializer


class PricePoint(BaseModel):
    sku: str
    price: Decimal
    discount: Decimal = Decimal("0")

    @field_serializer("price", "discount", when_used="json")
    def _as_number(self, v: Decimal) -> float:
        return float(v)


class PriceList(BaseModel):
    currency: str
    points: List[PricePoint]


def price_list_json(pl: PriceList) -> str:
    return pl.model_dump_json()
