import pytest
from pydantic import ValidationError

from app.signup import Signup


def test_email_normalized():
    assert Signup(username="ada", email="  Ada@Example.COM ").email == "ada@example.com"


def test_bad_username():
    with pytest.raises(ValidationError):
        Signup(username="ada lovelace", email="a@b.c")
