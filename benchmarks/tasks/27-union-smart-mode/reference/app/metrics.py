from typing import List, Union

from pydantic import BaseModel, Field


class Metric(BaseModel):
    name: str
    # Numeric when it parses as an int, otherwise a label (e.g. "n/a").
    value: Union[int, str] = Field(union_mode="left_to_right")


def parse_csv_row(row: str) -> Metric:
    name, value = row.split(",", 1)
    return Metric.model_validate({"name": name.strip(), "value": value.strip()})


def numeric_total(metrics: List[Metric]) -> int:
    return sum(m.value for m in metrics if isinstance(m.value, int))
