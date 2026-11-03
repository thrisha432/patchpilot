from typing import List

from pydantic import BaseModel


class Tag(BaseModel):
    name: str
    color: str = "gray"


class TagList(BaseModel):
    __root__: List[Tag]

    def names(self):
        return [t.name for t in self.__root__]


def parse_tags(data: list) -> TagList:
    return TagList.parse_obj(data)


def dump_tags(tags: TagList) -> list:
    return tags.dict()["__root__"]
