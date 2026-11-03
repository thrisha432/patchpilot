from datetime import date

from app.billing import build_invoice, invoice_payload, invoice_totals

LINES = [
    {"sku": "A", "description": "Seats", "quantity": 3, "unit_price": "29.00", "country": "de"},
    {"sku": "B", "description": "Support", "quantity": 1, "unit_price": "100", "country": "us"},
]


def test_invoice_totals():
    inv = build_invoice("INV-1", "  Acme  ", LINES, date(2024, 1, 31))
    assert inv.customer == "Acme" and inv.lines[0].country == "DE"
    assert invoice_totals(inv) == {"net": "187.00 EUR", "tax": "16.53 EUR", "gross": "203.53 EUR"}


def test_payload():
    payload = invoice_payload(build_invoice("INV-1", "Acme", LINES, date(2024, 1, 31)))
    assert payload["due"] == "2024-02-14" and "note" not in payload
