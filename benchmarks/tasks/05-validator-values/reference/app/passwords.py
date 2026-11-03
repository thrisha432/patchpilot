from pydantic import BaseModel, ValidationInfo, field_validator


class PasswordChange(BaseModel):
    new_password: str
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def strong_enough(cls, v):
        if len(v) < 8:
            raise ValueError("password too short")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info: ValidationInfo):
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("passwords do not match")
        return v
