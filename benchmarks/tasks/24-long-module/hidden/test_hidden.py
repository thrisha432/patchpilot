from datetime import date
from decimal import Decimal

import pytest

from app import billing as b


def test_money_and_format():
    assert b.money("2.345") == Decimal("2.35")
    assert b.format_money(Decimal("1234567.5")) == "1,234,567.50 EUR"
    assert b.format_money(Decimal("-12"), "USD") == "-12.00 USD"


def test_calendar():
    assert b.days_in_month(date(2024, 2, 10)) == 29
    assert b.month_bounds(date(2023, 12, 5)) == (date(2023, 12, 1), date(2023, 12, 31))
    assert b.billing_dates(date(2024, 1, 31), 3) == [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)]


def test_pricing():
    assert b.prorate(Decimal("31"), date(2024, 1, 1), date(2024, 1, 10)) == Decimal("10.00")
    assert b.usage_charge(1500) == Decimal("70.00")
    assert b.usage_charge(150_000) == Decimal("4110.00")
    assert b.discount(Decimal("80"), 25) == Decimal("60.00")
    assert b.annual_price(b.Plan.TEAM) == Decimal("990.00")
    assert b.add_vat(Decimal("100"), "se") == (Decimal("25.00"), Decimal("125.00"))
    assert b.late_fee(15, Decimal("200")) == Decimal("6.00")
    assert b.amortize(Decimal("12000"), Decimal("0"), 12) == Decimal("1000.00")


def test_misc():
    assert b.split_evenly(Decimal("10"), 3) == [Decimal("3.34"), Decimal("3.33"), Decimal("3.33")]
    assert b.invoice_number(2024, 42) == "INV-2024-000042"
    assert b.luhn_valid("4539 1488 0343 6467") and not b.luhn_valid("4539 1488 0343 6468")
    assert b.mask_card("4539-1488-0343-6467") == "************6467"
    with pytest.raises(ValueError):
        b.vat_rate("XX")


def test_group_by_country():
    inv = b.build_invoice("I", "C", [
        {"sku": "A", "description": "x", "quantity": 2, "unit_price": "5", "country": "fr"},
        {"sku": "B", "description": "y", "quantity": 1, "unit_price": "1", "country": "de"},
    ], date(2024, 5, 1))
    assert b.group_by_country(inv.lines) == {"DE": Decimal("1.00"), "FR": Decimal("10.00")}
