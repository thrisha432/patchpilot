from typing import Dict, List

from pydantic import BaseModel, parse_obj_as


class Reading(BaseModel):
    sensor: str
    value: float


def parse_readings(rows: list) -> List[Reading]:
    return parse_obj_as(List[Reading], rows)


def parse_thresholds(raw: dict) -> Dict[str, float]:
    return parse_obj_as(Dict[str, float], raw)
