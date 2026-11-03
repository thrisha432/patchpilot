from typing import List, Optional

from pydantic import BaseModel


class Profile(BaseModel):
    username: str
    bio: Optional[str] = None
    website: Optional[str] = None
    age: Optional[int] = None
    interests: List[str] = []


def profile_from_form(form: dict) -> Profile:
    return Profile(**{k: v for k, v in form.items() if v not in ("", None)})
