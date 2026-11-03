from app.api_errors import error_codes


def test_custom_validator_error():
    assert error_codes({"username": "a b c", "age": 1}) == {"username": ["INVALID"]}


def test_missing_age():
    assert error_codes({"username": "ada"}) == {"age": ["MISSING"]}
