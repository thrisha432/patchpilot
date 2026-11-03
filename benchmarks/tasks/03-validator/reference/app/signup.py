from pydantic import BaseModel, field_validator


class Signup(BaseModel):
    username: str
    email: str

    @field_validator("username")
    @classmethod
    def username_alnum(cls, v):
        if not v.isalnum():
            raise ValueError("username must be alphanumeric")
        return v

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v):
        v = v.strip().lower()
        if "@" not in v:
            raise ValueError("invalid email")
        return v
