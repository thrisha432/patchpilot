from app.client import fetch_weather, retry_copy, snapshot
from app.http import Cache, Response


def test_response_json_untouched():
    assert Response(200, '{"a": 1}').json() == {"a": 1}


def test_response_copy_untouched():
    r = retry_copy(Response(201, "{}"))
    assert isinstance(r, Response) and r.status == 201


def test_cache_dict_untouched():
    fetch_weather(Response(200, '{"city": "Rome", "temp_c": 20}'))
    assert "Rome" in snapshot()
    c = Cache()
    c.put("k", 1)
    assert c.dict() == {"k": 1}
