from pydantic import BaseModel, ConfigDict


def to_camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.title() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Shipment(ApiModel):
    tracking_number: str
    weight_kg: float
    is_express: bool = False


def to_wire(s: Shipment) -> str:
    return s.model_dump_json(by_alias=True)


def from_wire(raw: str) -> Shipment:
    return Shipment.model_validate_json(raw)
