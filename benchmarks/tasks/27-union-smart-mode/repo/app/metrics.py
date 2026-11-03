from typing import List, Union

from pydantic import BaseModel


class Metric(BaseModel):
    name: str
    # Numeric when it parses as an int, otherwise a label (e.g. "n/a").
    value: Union[int, str]


def parse_csv_row(row: str) -> Metric:
    name, value = row.split(",", 1)
    return Metric.parse_obj({"name": name.strip(), "value": value.strip()})


def numeric_total(metrics: List[Metric]) -> int:
    return sum(m.value for m in metrics if isinstance(m.value, int))
