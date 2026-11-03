import pytest
from pydantic import ValidationError

from app.catalog import Product

GOOD = dict(sku="ABC-1234", name="Mug", barcode="012345678905", sizes=["M"])


@pytest.mark.parametrize(
    "change",
    [{"barcode": "123"}, {"tags": ["a", "b", "c", "d"]}, {"sizes": []}, {"name": ""}],
)
def test_constraints_enforced(change):
    with pytest.raises(ValidationError):
        Product(**dict(GOOD, **change))


def test_three_tags_ok():
    assert len(Product(**dict(GOOD, tags=["a", "b", "c"])).tags) == 3
