from typing import List, Optional

from pydantic import BaseModel


class LineItem(BaseModel):
    sku: str
    quantity: int
    unit_price: float


class Order(BaseModel):
    id: str
    customer: str
    items: List[LineItem]
    note: Optional[str] = None
