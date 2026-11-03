import json
from typing import List

from pydantic import BaseModel, ConfigDict, Field


class Endpoint(BaseModel):
    path: str = Field(..., description="URL path")
    methods: List[str]

    model_config = ConfigDict(json_schema_extra={"example": {"path": "/items", "methods": ["GET"]}})


def endpoint_schema() -> dict:
    return Endpoint.model_json_schema()


def endpoint_schema_json() -> str:
    return json.dumps(Endpoint.model_json_schema(), indent=2)
