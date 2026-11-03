from app.http import Cache, Response
from app.models import Weather

_cache = Cache()


def fetch_weather(resp: Response) -> Weather:
    data = resp.json()
    weather = Weather.model_validate(data)
    _cache.put(weather.city, weather)
    return weather


def snapshot() -> dict:
    return _cache.dict()


def weather_payload(w: Weather) -> dict:
    return w.model_dump()


def retry_copy(resp: Response) -> Response:
    return resp.copy()
