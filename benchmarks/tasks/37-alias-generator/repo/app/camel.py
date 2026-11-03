from pydantic import BaseModel


def to_camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.title() for part in rest)


class ApiModel(BaseModel):
    class Config:
        alias_generator = to_camel
        allow_population_by_field_name = True


class Shipment(ApiModel):
    tracking_number: str
    weight_kg: float
    is_express: bool = False


def to_wire(s: Shipment) -> str:
    return s.json(by_alias=True)


def from_wire(raw: str) -> Shipment:
    return Shipment.parse_raw(raw)
