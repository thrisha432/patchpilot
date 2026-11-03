import pytest
from pydantic import ValidationError

from app.customers import Customer


def test_extra_forbidden():
    with pytest.raises(ValidationError):
        Customer(customer_id=1, full_name="Ada", email="a@x.io", vip=True)
