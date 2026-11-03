import pytest
from pydantic import ValidationError

from app.events import Click, parse_events


def test_wrong_type_rejected():
    with pytest.raises(ValidationError):
        Click(type="scroll", x=1, y=1)


def test_default_type():
    assert Click(x=0, y=0).type == "click"


def test_unknown_event_rejected():
    with pytest.raises(ValidationError):
        parse_events([{"type": "hover"}])
