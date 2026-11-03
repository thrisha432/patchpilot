from app.audit import AuditLog
from app.models import Order

log = AuditLog()


def place(raw: dict) -> Order:
    order = Order.parse_obj(raw)
    log.add(f"placed {order.id}")
    return order


def duplicate(order: Order, new_id: str) -> Order:
    clone = order.copy(deep=True, update={"id": new_id})
    log.add(f"duplicated {order.id} as {new_id}")
    return clone


def summary(order: Order) -> dict:
    return order.dict(include={"id", "total"})


def audit_snapshot() -> dict:
    return log.copy().dict()
