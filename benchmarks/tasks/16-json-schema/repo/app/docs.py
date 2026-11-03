from typing import List

from pydantic import BaseModel, Field


class Endpoint(BaseModel):
    path: str = Field(..., description="URL path")
    methods: List[str]

    class Config:
        schema_extra = {"example": {"path": "/items", "methods": ["GET"]}}


def endpoint_schema() -> dict:
    return Endpoint.schema()


def endpoint_schema_json() -> str:
    return Endpoint.schema_json(indent=2)
