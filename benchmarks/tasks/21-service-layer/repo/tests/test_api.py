import json
from datetime import datetime

from app.api import address_json, customer_response, update_email
from app.repository import get_customer, make_record

RECORD = dict(
    id=7, name="Ada", email=None, tags=["vip"], joined=datetime(2024, 1, 1),
    address={"street": "1 Main St", "city": "Oslo", "postcode": "n0 150"},
)


def test_customer_response():
    body = json.loads(customer_response(make_record(**dict(RECORD))))
    assert body["city"] == "Oslo" and body["address"]["postcode"] == "N0150"
    assert "joined" not in body and body["email"] is None


def test_update_email():
    c = get_customer(make_record(**dict(RECORD)))
    assert update_email(c, "ada@x.io").email == "ada@x.io"


def test_address_json():
    c = get_customer(make_record(**dict(RECORD)))
    assert json.loads(address_json(c))["postcode"] == "N0150"
