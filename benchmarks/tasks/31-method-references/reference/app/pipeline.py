import json
from typing import Callable, Dict, List

from pydantic import BaseModel


class Event(BaseModel):
    kind: str
    seq: int


def parse_all(rows: List[dict]) -> List[Event]:
    return list(map(Event.model_validate, rows))


def serializer(event: Event) -> Callable[[], str]:
    return event.model_dump_json


SINKS: Dict[str, Callable[[Event], dict]] = {"dict": Event.model_dump}


def to_sink(event: Event, sink: str) -> dict:
    return SINKS[sink](event)


def roundtrip(rows: List[dict]) -> List[dict]:
    return [json.loads(serializer(e)()) for e in parse_all(rows)]
