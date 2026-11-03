from pydantic import BaseModel, validator


class Signup(BaseModel):
    username: str
    email: str

    @validator("username")
    def username_alnum(cls, v):
        if not v.isalnum():
            raise ValueError("username must be alphanumeric")
        return v

    @validator("email")
    def normalize_email(cls, v):
        v = v.strip().lower()
        if "@" not in v:
            raise ValueError("invalid email")
        return v
