from app.client import fetch_weather, weather_payload
from app.http import Response


def test_fetch_and_payload():
    w = fetch_weather(Response(200, '{"city": "Oslo", "temp_c": "-3.5"}'))
    assert weather_payload(w) == {"city": "Oslo", "temp_c": -3.5}
