from typing import Optional

from pydantic import BaseModel, validator


def normalize_phone(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    digits = "".join(c for c in value if c.isdigit())
    if len(digits) < 7:
        raise ValueError("phone number too short")
    return "+" + digits


class Contact(BaseModel):
    name: str
    mobile: Optional[str] = None
    office: Optional[str] = None

    _normalize_mobile = validator("mobile", allow_reuse=True)(normalize_phone)
    _normalize_office = validator("office", allow_reuse=True)(normalize_phone)
