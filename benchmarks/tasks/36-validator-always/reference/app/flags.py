from typing import Dict, Optional

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class FeatureFlags(BaseModel):
    env: str = "dev"
    rollout: Dict[str, int] = {}
    owner: Optional[str] = Field(default=None, validate_default=True)

    @field_validator("rollout")
    @classmethod
    def percent(cls, v):
        for value in v.values():
            if not 0 <= value <= 100:
                raise ValueError("rollout must be 0-100")
        return v

    @field_validator("owner")
    @classmethod
    def default_owner(cls, v, info: ValidationInfo):
        return v or f"team-{info.data.get('env', 'dev')}"
