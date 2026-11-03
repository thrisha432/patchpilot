from pydantic import BaseModel, Extra, Field


class Customer(BaseModel):
    customer_id: int = Field(..., alias="customerId")
    full_name: str = Field(..., alias="fullName")
    email: str

    class Config:
        allow_population_by_field_name = True
        anystr_strip_whitespace = True
        extra = Extra.forbid


class AuditEntry(BaseModel):
    action: str
    actor: str

    class Config:
        allow_mutation = False
