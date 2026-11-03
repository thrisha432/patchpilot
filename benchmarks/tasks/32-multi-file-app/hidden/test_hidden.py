from types import SimpleNamespace

from app.cache import LRU
from app.models import Item, Supplier


def test_discontinued_optional():
    item = Item(sku="q", name="n", stock=1, supplier=Supplier(name="s", country="c"))
    assert item.discontinued is None


def test_lru_untouched():
    c = LRU(size=1)
    c.put("a", 1)
    c.put("b", 2)
    assert c.dict() == {"b": 2} and c.copy().dict() == {"b": 2}


def test_page_size_from_env(monkeypatch):
    monkeypatch.setenv("INV_PAGE_SIZE", "1")
    from app.service import load_items, page_json

    acme = SimpleNamespace(name="A", country="B")
    items = load_items([SimpleNamespace(sku=s, name=s, stock=1, supplier=acme, tags=[], discontinued=None) for s in "xy"])
    assert page_json(items, 1)["pages"] == 2
