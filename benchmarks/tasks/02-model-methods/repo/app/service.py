from app.models import Order


def load_order(payload: dict) -> Order:
    return Order.parse_obj(payload)


def load_order_json(raw: str) -> Order:
    return Order.parse_raw(raw)


def order_total(order: Order) -> float:
    return round(sum(i.quantity * i.unit_price for i in order.items), 2)


def public_view(order: Order) -> dict:
    return order.dict(exclude={"note"})


def to_json(order: Order) -> str:
    return order.json()


def with_note(order: Order, note: str) -> Order:
    return order.copy(update={"note": note})
