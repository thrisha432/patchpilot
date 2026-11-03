class LRU:
    """Tiny cache with a dict()-style snapshot; unrelated to Pydantic."""

    def __init__(self, size: int = 16):
        self.size = size
        self._data = {}

    def put(self, key, value):
        self._data.pop(key, None)
        self._data[key] = value
        while len(self._data) > self.size:
            self._data.pop(next(iter(self._data)))

    def dict(self):
        return dict(self._data)

    def copy(self):
        other = LRU(self.size)
        other._data = dict(self._data)
        return other
