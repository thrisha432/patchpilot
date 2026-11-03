from typing import Dict, List

from pydantic import BaseModel, TypeAdapter


class Reading(BaseModel):
    sensor: str
    value: float


def parse_readings(rows: list) -> List[Reading]:
    return TypeAdapter(List[Reading]).validate_python(rows)


def parse_thresholds(raw: dict) -> Dict[str, float]:
    return TypeAdapter(Dict[str, float]).validate_python(raw)
