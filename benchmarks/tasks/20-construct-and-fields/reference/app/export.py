import csv
import io
from typing import List

from pydantic import BaseModel


class Row(BaseModel):
    name: str
    qty: int
    price: float


def header() -> List[str]:
    return list(Row.model_fields.keys())


def trusted_rows(raw: List[dict]) -> List[Row]:
    # Data from our own database: skip validation for speed.
    return [Row.model_construct(**r) for r in raw]


def to_csv(rows: List[Row]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header(), lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow(r.model_dump())
    return buf.getvalue()
