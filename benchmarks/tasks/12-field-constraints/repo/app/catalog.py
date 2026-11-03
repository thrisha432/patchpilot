from typing import List

from pydantic import BaseModel, Field, conlist, constr

Sku = constr(regex=r"^[A-Z]{3}-\d{4}$")


class Product(BaseModel):
    sku: Sku
    name: str = Field(..., min_length=1, max_length=50)
    barcode: str = Field(..., regex=r"^\d{12}$")
    tags: List[str] = Field(default_factory=list, max_items=3)
    sizes: conlist(str, min_items=1)
