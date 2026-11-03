from types import SimpleNamespace

from app.service import cache_snapshot, load_items, page_json, restock

ACME = SimpleNamespace(name="Acme", country="DE")


def rec(sku, stock):
    return SimpleNamespace(sku=sku, name=f"item {sku}", stock=stock, supplier=ACME, tags=[], discontinued=None)


def test_load_and_page():
    items = load_items([rec("a1", 3), rec("b2", 0), rec("c3", 9)])
    body = page_json(items, 2)
    assert body["page"] == 2 and body["pages"] == 2
    assert body["items"][0]["sku"] == "C3" and body["items"][0]["supplier"]["name"] == "Acme"


def test_restock_and_cache():
    [item] = load_items([rec("z9", 1)])
    assert restock(item, 4).stock == 5 and item.stock == 1
    assert cache_snapshot()["Z9"] == 1
