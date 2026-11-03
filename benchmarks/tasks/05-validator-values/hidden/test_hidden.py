import pytest
from pydantic import ValidationError

from app.passwords import PasswordChange


def test_short_password_reports_one_error():
    # If new_password fails, the match check must not add a second error.
    with pytest.raises(ValidationError) as info:
        PasswordChange(new_password="short", confirm_password="different")
    assert len(info.value.errors()) == 1
