from pydantic import BaseModel, validator


class PasswordChange(BaseModel):
    new_password: str
    confirm_password: str

    @validator("new_password")
    def strong_enough(cls, v):
        if len(v) < 8:
            raise ValueError("password too short")
        return v

    @validator("confirm_password")
    def passwords_match(cls, v, values):
        if "new_password" in values and v != values["new_password"]:
            raise ValueError("passwords do not match")
        return v
