from app.api_errors import error_codes


def test_codes():
    assert error_codes({"age": "old"}) == {"username": ["MISSING"], "age": ["NOT_AN_INTEGER"]}
    assert error_codes({"username": "ab", "age": 3}) == {"username": ["TOO_SHORT"]}


def test_valid_payload():
    assert error_codes({"username": "ada", "age": 36}) == {}
