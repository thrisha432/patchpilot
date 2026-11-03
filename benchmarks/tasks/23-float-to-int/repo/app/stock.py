from typing import List

from pydantic import BaseModel


class StockLevel(BaseModel):
    sku: str
    units: int


def from_scale(sku: str, reading: float) -> StockLevel:
    # Scales report fractional units; stock counts whole units (truncate).
    return StockLevel(sku=sku, units=reading)


def total_units(levels: List[StockLevel]) -> int:
    return sum(level.units for level in levels)
