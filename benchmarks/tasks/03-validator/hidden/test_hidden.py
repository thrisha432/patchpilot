import pytest
from pydantic import ValidationError

from app.signup import Signup


def test_bad_email():
    with pytest.raises(ValidationError):
        Signup(username="ada", email="not-an-email")


def test_username_kept():
    assert Signup(username="Ada99", email="a@b.c").username == "Ada99"
