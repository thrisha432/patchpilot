from typing import List

from pydantic import BaseModel, SerializeAsAny


class Channel(BaseModel):
    kind: str


class EmailChannel(Channel):
    kind: str = "email"
    address: str


class SmsChannel(Channel):
    kind: str = "sms"
    number: str


class Subscription(BaseModel):
    user: str
    channels: List[SerializeAsAny[Channel]]


def export(sub: Subscription) -> dict:
    return sub.model_dump()
