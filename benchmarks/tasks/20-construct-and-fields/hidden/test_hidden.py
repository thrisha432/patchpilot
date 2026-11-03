from app.export import trusted_rows


def test_construct_skips_validation():
    # construct() trusts its input: no coercion happens.
    assert trusted_rows([{"name": "pen", "qty": "2", "price": 1.5}])[0].qty == "2"
