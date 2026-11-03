from typing import Optional

from pydantic import BaseModel


class ProfilePatch(BaseModel):
    display_name: Optional[str] = None
    bio: Optional[str] = None
    newsletter: Optional[bool] = None


def apply_patch(current: dict, body: dict) -> dict:
    patch = ProfilePatch.parse_obj(body)
    changed = sorted(patch.__fields_set__)
    updated = dict(current, **patch.dict(exclude_unset=True))
    updated["_changed"] = changed
    return updated
