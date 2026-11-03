from typing import List, Optional

from pydantic import BaseModel, validator


class Supplier(BaseModel):
    name: str
    country: str

    class Config:
        orm_mode = True


class Item(BaseModel):
    sku: str
    name: str
    stock: int
    supplier: Supplier
    tags: List[str] = []
    discontinued: Optional[bool]

    @validator("sku")
    def sku_upper(cls, v):
        return v.upper()

    class Config:
        orm_mode = True
