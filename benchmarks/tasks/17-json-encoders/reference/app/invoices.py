from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_serializer


class Invoice(BaseModel):
    number: str
    issued_at: datetime
    amount: Decimal

    @field_serializer("issued_at", when_used="json")
    def _date(self, v: datetime) -> str:
        return v.strftime("%Y-%m-%d")

    @field_serializer("amount", when_used="json")
    def _amount(self, v: Decimal) -> str:
        return f"{v:.2f}"


def invoice_json(inv: Invoice) -> str:
    return inv.model_dump_json()
