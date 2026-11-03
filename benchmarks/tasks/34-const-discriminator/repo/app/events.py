from typing import List, Union

from pydantic import BaseModel, Field, parse_obj_as


class Click(BaseModel):
    type: str = Field("click", const=True)
    x: int
    y: int


class Scroll(BaseModel):
    type: str = Field("scroll", const=True)
    delta: int


Event = Union[Click, Scroll]


def parse_events(raw: List[dict]) -> List[Event]:
    return parse_obj_as(List[Event], raw)
