import pytest
from pydantic import ValidationError

from app.articles import Article


def test_empty_string_gives_no_tags():
    assert Article(title="x", tags="").tags == []


def test_non_string_item_rejected():
    with pytest.raises(ValidationError):
        Article(title="x", tags=[{"a": 1}])
