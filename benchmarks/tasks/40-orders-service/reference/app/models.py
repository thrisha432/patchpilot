from typing import List

from pydantic import BaseModel, ConfigDict, model_validator


class Line(BaseModel):
    sku: str
    qty: int
    price: float


class Order(BaseModel):
    id: str
    lines: List[Line]
    total: float = 0.0

    model_config = ConfigDict(validate_assignment=True)

    @model_validator(mode="before")
    @classmethod
    def compute_total(cls, values):
        if isinstance(values, dict):
            lines = values.get("lines") or []
            total = 0.0
            for line in lines:
                item = line if isinstance(line, dict) else line.model_dump()
                total += item["qty"] * item["price"]
            values = dict(values, total=round(total, 2))
        return values
