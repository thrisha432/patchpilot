import json as _json


class Response:
    """A minimal HTTP response object (NOT a Pydantic model)."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body

    def json(self):
        return _json.loads(self.body)

    def copy(self):
        return Response(self.status, self.body)


class Cache:
    def __init__(self):
        self._data = {}

    def dict(self):
        return dict(self._data)

    def put(self, key, value):
        self._data[key] = value
