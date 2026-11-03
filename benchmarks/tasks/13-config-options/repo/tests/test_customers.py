import pytest
from pydantic import ValidationError

from app.customers import AuditEntry, Customer


def test_alias_and_field_name():
    a = Customer(customerId=1, fullName="Ada", email="a@x.io")
    b = Customer(customer_id=1, full_name="Ada", email="a@x.io")
    assert a == b


def test_whitespace_stripped():
    assert Customer(customer_id=1, full_name="  Ada  ", email="a@x.io").full_name == "Ada"


def test_audit_entry_immutable():
    entry = AuditEntry(action="login", actor="ada")
    with pytest.raises((TypeError, ValidationError)):
        entry.actor = "eve"
