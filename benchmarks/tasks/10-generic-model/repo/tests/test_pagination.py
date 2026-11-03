from app.pagination import Product, product_page


def test_items_are_products():
    page = product_page({"items": [{"sku": "A", "price": "9.5"}], "page": 1, "total": 3})
    assert isinstance(page.items[0], Product) and page.items[0].price == 9.5


def test_has_next():
    assert product_page({"items": [], "page": 1, "total": 3}).has_next(page_size=2)
