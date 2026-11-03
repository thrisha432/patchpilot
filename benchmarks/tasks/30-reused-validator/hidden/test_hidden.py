import pytest
from pydantic import ValidationError

from app.contacts import Contact


def test_short_number_rejected():
    with pytest.raises(ValidationError):
        Contact(name="x", office="12")


def test_optional():
    assert Contact(name="x").mobile is None
