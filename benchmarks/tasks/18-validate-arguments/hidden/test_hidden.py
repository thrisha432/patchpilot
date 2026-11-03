import pytest
from pydantic import ValidationError

from app.mathutil import average, repeat


def test_rejects_bad_arguments():
    with pytest.raises(ValidationError):
        average(["x"])
    with pytest.raises(ValidationError):
        repeat("a", "many")


def test_default():
    assert repeat("z") == "zz"
