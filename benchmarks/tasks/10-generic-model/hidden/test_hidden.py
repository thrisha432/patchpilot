import pytest
from pydantic import ValidationError

from app.pagination import product_page


def test_last_page():
    assert not product_page({"items": [], "page": 2, "total": 3}).has_next(page_size=2)


def test_bad_item_rejected():
    with pytest.raises(ValidationError):
        product_page({"items": [{"sku": "A"}], "page": 1, "total": 1})
