from typing import Optional

from pydantic import BaseModel


class ProfilePatch(BaseModel):
    display_name: Optional[str] = None
    bio: Optional[str] = None
    newsletter: Optional[bool] = None


def apply_patch(current: dict, body: dict) -> dict:
    patch = ProfilePatch.model_validate(body)
    changed = sorted(patch.model_fields_set)
    updated = dict(current, **patch.model_dump(exclude_unset=True))
    updated["_changed"] = changed
    return updated
