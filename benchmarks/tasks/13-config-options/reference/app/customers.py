from pydantic import BaseModel, ConfigDict, Field


class Customer(BaseModel):
    customer_id: int = Field(..., alias="customerId")
    full_name: str = Field(..., alias="fullName")
    email: str

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True, extra="forbid")


class AuditEntry(BaseModel):
    action: str
    actor: str

    model_config = ConfigDict(frozen=True)
