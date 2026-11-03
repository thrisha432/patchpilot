import pytest
from pydantic import ValidationError

from app.passwords import PasswordChange


def test_ok():
    assert PasswordChange(new_password="s3cret-pass", confirm_password="s3cret-pass")


def test_mismatch():
    with pytest.raises(ValidationError):
        PasswordChange(new_password="s3cret-pass", confirm_password="other-pass")
