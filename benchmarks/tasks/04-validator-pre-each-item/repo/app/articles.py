from typing import List

from pydantic import BaseModel, validator


class Article(BaseModel):
    title: str
    tags: List[str]

    @validator("tags", pre=True)
    def split_tags(cls, v):
        if isinstance(v, str):
            return [t for t in (p.strip() for p in v.split(",")) if t]
        return v

    @validator("tags", each_item=True)
    def tag_lower(cls, v):
        return v.lower()
