from typing import List

from pydantic import validate_arguments


@validate_arguments
def average(values: List[float]) -> float:
    return sum(values) / len(values)


@validate_arguments
def repeat(text: str, times: int = 2) -> str:
    return text * times
