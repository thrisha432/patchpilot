import json

from app.models import Customer
from app.repository import get_customer


def customer_response(record) -> str:
    customer = get_customer(record)
    body = customer.model_dump(exclude={"joined"})
    body["city"] = customer.address.city
    return json.dumps(body, sort_keys=True)


def update_email(customer: Customer, email: str) -> Customer:
    return customer.model_copy(update={"email": email})


def address_json(customer: Customer) -> str:
    return customer.address.model_dump_json()
