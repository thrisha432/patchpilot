from types import SimpleNamespace

from app.models import Customer


def make_record(**fields):
    """What the ORM returns: objects with attributes, nested."""
    address = SimpleNamespace(**fields.pop("address"))
    return SimpleNamespace(address=address, **fields)


def get_customer(record) -> Customer:
    return Customer.from_orm(record)
