from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator


class Supplier(BaseModel):
    name: str
    country: str

    model_config = ConfigDict(from_attributes=True)


class Item(BaseModel):
    sku: str
    name: str
    stock: int
    supplier: Supplier
    tags: List[str] = []
    discontinued: Optional[bool] = None

    @field_validator("sku")
    @classmethod
    def sku_upper(cls, v):
        return v.upper()

    model_config = ConfigDict(from_attributes=True)
