from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class Invoice(BaseModel):
    number: str
    issued_at: datetime
    amount: Decimal

    class Config:
        json_encoders = {
            datetime: lambda v: v.strftime("%Y-%m-%d"),
            Decimal: lambda v: f"{v:.2f}",
        }


def invoice_json(inv: Invoice) -> str:
    return inv.json()
