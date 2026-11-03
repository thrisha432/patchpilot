import json
from datetime import datetime
from decimal import Decimal

from app.invoices import Invoice, invoice_json


def test_custom_encoding():
    inv = Invoice(number="A1", issued_at=datetime(2024, 3, 5, 14, 30), amount=Decimal("12.5"))
    assert json.loads(invoice_json(inv)) == {"number": "A1", "issued_at": "2024-03-05", "amount": "12.50"}
