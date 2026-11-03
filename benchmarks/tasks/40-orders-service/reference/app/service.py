from app.audit import AuditLog
from app.models import Order

log = AuditLog()


def place(raw: dict) -> Order:
    order = Order.model_validate(raw)
    log.add(f"placed {order.id}")
    return order


def duplicate(order: Order, new_id: str) -> Order:
    clone = order.model_copy(deep=True, update={"id": new_id})
    log.add(f"duplicated {order.id} as {new_id}")
    return clone


def summary(order: Order) -> dict:
    return order.model_dump(include={"id", "total"})


def audit_snapshot() -> dict:
    return log.copy().dict()
