from typing import List

from pydantic import BaseModel, RootModel


class Tag(BaseModel):
    name: str
    color: str = "gray"


class TagList(RootModel[List[Tag]]):
    def names(self):
        return [t.name for t in self.root]


def parse_tags(data: list) -> TagList:
    return TagList.model_validate(data)


def dump_tags(tags: TagList) -> list:
    return tags.model_dump()
