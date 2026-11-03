from typing import List

from pydantic import BaseModel


class Order(BaseModel):
    id: int
    items: List[str]
    total: float
