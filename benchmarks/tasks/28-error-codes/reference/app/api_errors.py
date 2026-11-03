from typing import Dict, List

from pydantic import BaseModel, Field, ValidationError, field_validator


class CreateUser(BaseModel):
    username: str = Field(..., min_length=3)
    age: int

    @field_validator("username")
    @classmethod
    def no_spaces(cls, v):
        if " " in v:
            raise ValueError("username must not contain spaces")
        return v


# Map Pydantic's error types to our stable public error codes.
TYPE_CODES = {
    "missing": "MISSING",
    "int_parsing": "NOT_AN_INTEGER",
    "string_too_short": "TOO_SHORT",
}


def error_codes(payload: dict) -> Dict[str, List[str]]:
    try:
        CreateUser(**payload)
    except ValidationError as exc:
        out: Dict[str, List[str]] = {}
        for err in exc.errors():
            code = TYPE_CODES.get(err["type"], "INVALID")
            out.setdefault(str(err["loc"][0]), []).append(code)
        return out
    return {}
