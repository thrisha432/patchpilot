import pytest
from pydantic import ValidationError

from app.catalog import Product

GOOD = dict(sku="ABC-1234", name="Mug", barcode="012345678905", sizes=["M"])


def test_valid():
    assert Product(**GOOD).sku == "ABC-1234"


def test_bad_sku():
    with pytest.raises(ValidationError):
        Product(**dict(GOOD, sku="abc-12"))
