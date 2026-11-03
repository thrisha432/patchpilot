from app.legacy import Record
from app.models import Order


def get_order(raw: dict) -> Order:
    return Order.model_validate(raw)


def get_record(raw: dict) -> Record:
    return Record(**raw)
