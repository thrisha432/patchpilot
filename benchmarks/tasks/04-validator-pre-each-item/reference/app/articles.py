from typing import List

from pydantic import BaseModel, field_validator


class Article(BaseModel):
    title: str
    tags: List[str]

    @field_validator("tags", mode="before")
    @classmethod
    def split_tags(cls, v):
        if isinstance(v, str):
            return [t for t in (p.strip() for p in v.split(",")) if t]
        return v

    @field_validator("tags")
    @classmethod
    def tag_lower(cls, v):
        return [t.lower() for t in v]
