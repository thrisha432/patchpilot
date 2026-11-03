from typing import List

from pydantic import BaseModel, Field, conlist, constr

Sku = constr(pattern=r"^[A-Z]{3}-\d{4}$")


class Product(BaseModel):
    sku: Sku
    name: str = Field(..., min_length=1, max_length=50)
    barcode: str = Field(..., pattern=r"^\d{12}$")
    tags: List[str] = Field(default_factory=list, max_length=3)
    sizes: conlist(str, min_length=1)
