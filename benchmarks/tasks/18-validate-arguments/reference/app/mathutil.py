from typing import List

from pydantic import validate_call


@validate_call
def average(values: List[float]) -> float:
    return sum(values) / len(values)


@validate_call
def repeat(text: str, times: int = 2) -> str:
    return text * times
