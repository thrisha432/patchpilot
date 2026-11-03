import json
from typing import List

from app.cache import LRU
from app.models import Item
from app.pages import Page
from app.settings import Settings

_cache = LRU()


def load_items(records) -> List[Item]:
    items = [Item.from_orm(r) for r in records]
    for item in items:
        _cache.put(item.sku, item.stock)
    return items


def page_of(items: List[Item], page: int) -> Page[Item]:
    size = Settings().page_size
    start = (page - 1) * size
    pages = max(1, -(-len(items) // size))
    return Page[Item](items=items[start : start + size], page=page, pages=pages)


def page_json(items: List[Item], page: int) -> dict:
    return json.loads(page_of(items, page).json())


def restock(item: Item, amount: int) -> Item:
    return item.copy(update={"stock": item.stock + amount})


def cache_snapshot() -> dict:
    return _cache.copy().dict()
