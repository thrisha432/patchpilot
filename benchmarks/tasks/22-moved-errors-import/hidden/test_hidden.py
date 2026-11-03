from app.payments import validate_payment


def test_only_currency_missing():
    assert validate_payment({"amount": 1})[1] == ["currency"]
