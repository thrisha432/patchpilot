from datetime import date, timedelta
from typing import Optional

from pydantic import BaseModel, root_validator


class Booking(BaseModel):
    start: date
    end: date
    nights: Optional[int] = None

    @root_validator(pre=True)
    def default_end(cls, values):
        if "end" not in values and "start" in values and "nights" in values:
            start = date.fromisoformat(str(values["start"]))
            values = dict(values, end=start + timedelta(days=int(values["nights"])))
        return values

    @root_validator(skip_on_failure=True)
    def check_order(cls, values):
        if values["end"] <= values["start"]:
            raise ValueError("end must be after start")
        values["nights"] = (values["end"] - values["start"]).days
        return values
