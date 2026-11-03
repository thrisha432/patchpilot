from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models import Address, Customer


def test_email_optional():
    c = Customer(id=1, name="A", address=Address(street="s", city="c", postcode="p"), joined=datetime(2024, 1, 1))
    assert c.email is None


def test_max_three_tags():
    with pytest.raises(ValidationError):
        Customer(
            id=1, name="A", email=None, tags=["a", "b", "c", "d"],
            address=Address(street="s", city="c", postcode="p"), joined=datetime(2024, 1, 1),
        )
