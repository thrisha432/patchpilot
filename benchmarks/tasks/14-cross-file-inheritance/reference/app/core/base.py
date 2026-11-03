from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Entity(BaseModel):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
