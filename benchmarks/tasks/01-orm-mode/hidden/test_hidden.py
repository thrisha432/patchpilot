import pytest
from pydantic import ValidationError

from app.models import UserRow, user_from_row


def test_empty_roles():
    assert user_from_row(UserRow(2, "Bob", "b@x.io", [])).roles == []


def test_invalid_row_rejected():
    with pytest.raises(ValidationError):
        user_from_row(UserRow("not-an-int", "Bob", "b@x.io", []))
