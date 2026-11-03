"""A legacy serialization layer that predates Pydantic. Its API happens to look similar."""

import json


class Record:
    def __init__(self, **fields):
        self._fields = dict(fields)

    def dict(self):
        return {"type": "record", **self._fields}

    def json(self):
        return json.dumps(self.dict(), sort_keys=True)


class Snapshot:
    def __init__(self, payload, version):
        self.payload = payload
        self.version = version

    @classmethod
    def parse_obj(cls, data):
        return cls(payload=data["payload"], version=int(data.get("version", 1)))

    def copy(self):
        return Snapshot(dict(self.payload), self.version)
