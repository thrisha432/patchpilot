import json
from datetime import datetime
from decimal import Decimal

from app.invoices import Invoice, invoice_json


def test_python_values_unchanged():
    inv = Invoice(number="B2", issued_at=datetime(2024, 1, 2), amount=Decimal("3"))
    assert inv.amount == Decimal("3") and inv.issued_at.year == 2024


def test_rounding():
    inv = Invoice(number="C3", issued_at=datetime(2024, 1, 2), amount=Decimal("7.005"))
    assert json.loads(invoice_json(inv))["amount"] in ("7.00", "7.01")
