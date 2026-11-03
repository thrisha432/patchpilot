from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Address(BaseModel):
    street: str
    city: str
    postcode: str

    @field_validator("postcode")
    @classmethod
    def normalize_postcode(cls, v):
        return v.upper().replace(" ", "")

    model_config = ConfigDict(from_attributes=True)


class Customer(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    address: Address
    tags: List[str] = Field(default_factory=list, max_length=3)
    joined: datetime

    model_config = ConfigDict(from_attributes=True)
