from typing import Dict, Optional

from pydantic import BaseModel, validator


class FeatureFlags(BaseModel):
    env: str = "dev"
    rollout: Dict[str, int] = {}
    owner: Optional[str] = None

    @validator("rollout", each_item=True)
    def percent(cls, v):
        if not 0 <= v <= 100:
            raise ValueError("rollout must be 0-100")
        return v

    @validator("owner", always=True)
    def default_owner(cls, v, values):
        return v or f"team-{values.get('env', 'dev')}"
