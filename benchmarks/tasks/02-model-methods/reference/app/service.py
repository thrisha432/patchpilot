from app.models import Order


def load_order(payload: dict) -> Order:
    return Order.model_validate(payload)


def load_order_json(raw: str) -> Order:
    return Order.model_validate_json(raw)


def order_total(order: Order) -> float:
    return round(sum(i.quantity * i.unit_price for i in order.items), 2)


def public_view(order: Order) -> dict:
    return order.model_dump(exclude={"note"})


def to_json(order: Order) -> str:
    return order.model_dump_json()


def with_note(order: Order, note: str) -> Order:
    return order.model_copy(update={"note": note})
