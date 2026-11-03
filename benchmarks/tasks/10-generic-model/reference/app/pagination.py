from typing import Generic, List, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: List[T]
    page: int
    total: int

    def has_next(self, page_size: int) -> bool:
        return self.page * page_size < self.total


class Product(BaseModel):
    sku: str
    price: float


def product_page(raw: dict) -> "Page[Product]":
    return Page[Product].model_validate(raw)
