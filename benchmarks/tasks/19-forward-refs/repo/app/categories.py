from typing import List, Optional

from pydantic import BaseModel


class Category(BaseModel):
    name: str
    children: List["Category"] = []
    parent_name: Optional[str] = None


Category.update_forward_refs()


def build_tree(spec: dict) -> Category:
    return Category.parse_obj(spec)


def depth(c: Category) -> int:
    return 1 + max((depth(x) for x in c.children), default=0)
