from datetime import date, timedelta
from typing import Any, Optional

from pydantic import BaseModel, model_validator


class Booking(BaseModel):
    start: date
    end: date
    nights: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def default_end(cls, values: Any) -> Any:
        if isinstance(values, dict) and "end" not in values and "start" in values and "nights" in values:
            start = date.fromisoformat(str(values["start"]))
            values = dict(values, end=start + timedelta(days=int(values["nights"])))
        return values

    @model_validator(mode="after")
    def check_order(self):
        if self.end <= self.start:
            raise ValueError("end must be after start")
        self.nights = (self.end - self.start).days
        return self
