from datetime import datetime

from pydantic import BaseModel


class Entity(BaseModel):
    id: int
    created_at: datetime

    class Config:
        orm_mode = True
