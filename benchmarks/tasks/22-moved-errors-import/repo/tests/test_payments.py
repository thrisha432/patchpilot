from app.payments import validate_payment


def test_ok():
    payment, errors = validate_payment({"amount": "9.99", "currency": "EUR"})
    assert payment.amount == 9.99 and errors == []


def test_errors_listed():
    payment, errors = validate_payment({"amount": "lots"})
    assert payment is None and errors == ["amount", "currency"]
