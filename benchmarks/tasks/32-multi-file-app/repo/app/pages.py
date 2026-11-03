from typing import Generic, List, TypeVar

from pydantic.generics import GenericModel

T = TypeVar("T")


class Page(GenericModel, Generic[T]):
    items: List[T]
    page: int
    pages: int
