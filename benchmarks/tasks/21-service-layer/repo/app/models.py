from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, validator


class Address(BaseModel):
    street: str
    city: str
    postcode: str

    @validator("postcode")
    def normalize_postcode(cls, v):
        return v.upper().replace(" ", "")

    class Config:
        orm_mode = True


class Customer(BaseModel):
    id: int
    name: str
    email: Optional[str]
    address: Address
    tags: List[str] = Field(default_factory=list, max_items=3)
    joined: datetime

    class Config:
        orm_mode = True
