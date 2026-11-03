from typing import Optional

from pydantic import BaseModel, field_validator


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

    normalize_phones = field_validator("mobile", "office")(normalize_phone)
