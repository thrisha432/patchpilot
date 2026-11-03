from typing import List, Optional

from pydantic import BaseModel


class Category(BaseModel):
    name: str
    children: List["Category"] = []
    parent_name: Optional[str] = None


Category.model_rebuild()


def build_tree(spec: dict) -> Category:
    return Category.model_validate(spec)


def depth(c: Category) -> int:
    return 1 + max((depth(x) for x in c.children), default=0)
