import json

from app.docs import endpoint_schema, endpoint_schema_json


def test_schema_properties():
    schema = endpoint_schema()
    assert set(schema["properties"]) == {"path", "methods"}
    assert schema["properties"]["path"]["description"] == "URL path"


def test_schema_json_is_indented_json():
    text = endpoint_schema_json()
    assert "\n  " in text and json.loads(text)["title"] == "Endpoint"
