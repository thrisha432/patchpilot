from typing import List

from pydantic import BaseModel, root_validator


class Line(BaseModel):
    sku: str
    qty: int
    price: float


class Order(BaseModel):
    id: str
    lines: List[Line]
    total: float = 0.0

    @root_validator
    def compute_total(cls, values):
        lines = values.get("lines") or []
        values["total"] = round(sum(l.qty * l.price for l in lines), 2)
        return values

    class Config:
        validate_assignment = True
