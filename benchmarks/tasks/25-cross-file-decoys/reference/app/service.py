from app.legacy import Snapshot
from app.repository import get_order, get_record


def export_order(raw):
    order = get_order(raw)
    return order.model_dump()


def export_record(raw):
    record = get_record(raw)
    return record.dict()


def record_json(raw):
    return get_record(raw).json()


def restore(data):
    snap = Snapshot.parse_obj(data)
    return snap.copy()
