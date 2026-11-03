"""Billing utilities: pricing, proration, tax, invoice assembly and formatting.

Most of this module is plain Python and must not change during a Pydantic migration.
"""

import math
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Dict, Iterable, List, Optional, Tuple

from pydantic import BaseModel, Field, validator

CENT = Decimal("0.01")
VAT_RATES: Dict[str, Decimal] = {
    "DE": Decimal("0.19"),
    "FR": Decimal("0.20"),
    "NL": Decimal("0.21"),
    "SE": Decimal("0.25"),
    "US": Decimal("0.00"),
}
TIER_LIMITS: List[Tuple[int, Decimal]] = [
    (1_000, Decimal("0.050")),
    (10_000, Decimal("0.040")),
    (100_000, Decimal("0.030")),
]
OVERFLOW_RATE = Decimal("0.020")


class Plan(str, Enum):
    FREE = "free"
    PRO = "pro"
    TEAM = "team"
    ENTERPRISE = "enterprise"


PLAN_PRICES: Dict[Plan, Decimal] = {
    Plan.FREE: Decimal("0"),
    Plan.PRO: Decimal("29"),
    Plan.TEAM: Decimal("99"),
    Plan.ENTERPRISE: Decimal("499"),
}


def money(value) -> Decimal:
    """Round to cents, half up (banker's rounding is wrong for invoices)."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def format_money(amount: Decimal, currency: str = "EUR") -> str:
    sign = "-" if amount < 0 else ""
    whole, _, frac = f"{abs(money(amount)):.2f}".partition(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return f"{sign}{','.join(groups)}.{frac} {currency}"


def days_in_month(d: date) -> int:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return (nxt - date(d.year, d.month, 1)).days


def month_bounds(d: date) -> Tuple[date, date]:
    start = date(d.year, d.month, 1)
    return start, start + timedelta(days=days_in_month(d) - 1)


def prorate(amount: Decimal, start: date, end: date) -> Decimal:
    """Charge for the days [start, end] of one month, inclusive."""
    if end < start:
        raise ValueError("end before start")
    if (start.year, start.month) != (end.year, end.month):
        raise ValueError("proration spans months")
    used = (end - start).days + 1
    return money(amount * used / days_in_month(start))


def usage_charge(units: int) -> Decimal:
    """Graduated pricing: each tier's rate applies only to the units inside it."""
    if units < 0:
        raise ValueError("negative usage")
    total = Decimal("0")
    lower = 0
    for limit, rate in TIER_LIMITS:
        if units <= lower:
            break
        in_tier = min(units, limit) - lower
        total += in_tier * rate
        lower = limit
    if units > lower:
        total += (units - lower) * OVERFLOW_RATE
    return money(total)


def vat_rate(country: str) -> Decimal:
    try:
        return VAT_RATES[country.upper()]
    except KeyError:
        raise ValueError(f"unsupported country {country!r}") from None


def add_vat(net: Decimal, country: str) -> Tuple[Decimal, Decimal]:
    tax = money(net * vat_rate(country))
    return tax, money(net + tax)


def discount(amount: Decimal, percent: int) -> Decimal:
    if not 0 <= percent <= 100:
        raise ValueError("percent out of range")
    return money(amount * (100 - percent) / 100)


def split_evenly(total: Decimal, parts: int) -> List[Decimal]:
    """Split into `parts` cent amounts that add up exactly to `total`."""
    if parts <= 0:
        raise ValueError("parts must be positive")
    cents = int(money(total) * 100)
    base, extra = divmod(cents, parts)
    return [Decimal(base + (1 if i < extra else 0)) / 100 for i in range(parts)]


def annual_price(plan: Plan, months_free: int = 2) -> Decimal:
    return money(PLAN_PRICES[plan] * (12 - months_free))


def billing_dates(first: date, count: int) -> List[date]:
    """Same day each month, clamped to the month's last day (Jan 31 -> Feb 28)."""
    out = []
    year, month = first.year, first.month
    for _ in range(count):
        last = days_in_month(date(year, month, 1))
        out.append(date(year, month, min(first.day, last)))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def invoice_number(year: int, sequence: int, prefix: str = "INV") -> str:
    if sequence <= 0 or sequence >= 1_000_000:
        raise ValueError("sequence out of range")
    return f"{prefix}-{year}-{sequence:06d}"


def luhn_valid(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 2:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def mask_card(number: str) -> str:
    digits = "".join(c for c in number if c.isdigit())
    return "*" * (len(digits) - 4) + digits[-4:]


def amortize(principal: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    """Monthly payment for a fixed-rate loan."""
    if months <= 0:
        raise ValueError("months must be positive")
    r = float(annual_rate) / 12
    if r == 0:
        return money(principal / months)
    payment = float(principal) * r / (1 - math.pow(1 + r, -months))
    return money(Decimal(str(payment)))


def group_by_country(lines: Iterable["InvoiceLine"]) -> Dict[str, Decimal]:
    out: Dict[str, Decimal] = {}
    for line in lines:
        out[line.country] = money(out.get(line.country, Decimal("0")) + line.net)
    return dict(sorted(out.items()))


def late_fee(days_late: int, amount: Decimal) -> Decimal:
    """1% per started week late, capped at 10%."""
    if days_late <= 0:
        return Decimal("0.00")
    weeks = math.ceil(days_late / 7)
    return money(amount * min(weeks, 10) / 100)


class InvoiceLine(BaseModel):
    sku: str
    description: str
    quantity: int = Field(..., ge=1)
    unit_price: Decimal
    country: str = "DE"

    @validator("country")
    def upper_country(cls, v):
        return v.upper()

    @property
    def net(self) -> Decimal:
        return money(self.unit_price * self.quantity)


class Invoice(BaseModel):
    number: str
    customer: str
    lines: List[InvoiceLine]
    issued: date
    due_days: int = 14
    note: Optional[str] = None

    class Config:
        anystr_strip_whitespace = True

    def due(self) -> date:
        return self.issued + timedelta(days=self.due_days)


def build_invoice(number: str, customer: str, raw_lines: List[dict], issued: date) -> Invoice:
    return Invoice(number=number, customer=customer, lines=[InvoiceLine.parse_obj(r) for r in raw_lines], issued=issued)


def invoice_totals(inv: Invoice) -> Dict[str, str]:
    net = money(sum((line.net for line in inv.lines), Decimal("0")))
    tax = money(sum((add_vat(line.net, line.country)[0] for line in inv.lines), Decimal("0")))
    return {"net": format_money(net), "tax": format_money(tax), "gross": format_money(net + tax)}


def invoice_payload(inv: Invoice) -> dict:
    data = inv.dict(exclude={"note"})
    data["due"] = inv.due().isoformat()
    return data
