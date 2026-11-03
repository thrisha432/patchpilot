import pytest
from pydantic import ValidationError

from app.tags import dump_tags, parse_tags


def test_empty():
    assert dump_tags(parse_tags([])) == []


def test_invalid_item():
    with pytest.raises(ValidationError):
        parse_tags([{"color": "red"}])
