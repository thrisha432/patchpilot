from typing import Dict, List

from pydantic import BaseModel, Field, ValidationError, validator


class CreateUser(BaseModel):
    username: str = Field(..., min_length=3)
    age: int

    @validator("username")
    def no_spaces(cls, v):
        if " " in v:
            raise ValueError("username must not contain spaces")
        return v


# Map Pydantic's error messages to our stable public error codes.
MESSAGE_CODES = {
    "field required": "MISSING",
    "value is not a valid integer": "NOT_AN_INTEGER",
    "ensure this value has at least": "TOO_SHORT",
}


def error_codes(payload: dict) -> Dict[str, List[str]]:
    try:
        CreateUser(**payload)
    except ValidationError as exc:
        out: Dict[str, List[str]] = {}
        for err in exc.errors():
            code = next((c for m, c in MESSAGE_CODES.items() if err["msg"].startswith(m)), "INVALID")
            out.setdefault(str(err["loc"][0]), []).append(code)
        return out
    return {}
