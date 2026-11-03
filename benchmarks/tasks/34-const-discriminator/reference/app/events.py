from typing import List, Literal, Union

from pydantic import BaseModel, TypeAdapter


class Click(BaseModel):
    type: Literal["click"] = "click"
    x: int
    y: int


class Scroll(BaseModel):
    type: Literal["scroll"] = "scroll"
    delta: int


Event = Union[Click, Scroll]


def parse_events(raw: List[dict]) -> List[Event]:
    return TypeAdapter(List[Event]).validate_python(raw)
