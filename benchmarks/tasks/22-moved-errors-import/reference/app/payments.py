from pydantic import BaseModel, ValidationError


class Payment(BaseModel):
    amount: float
    currency: str


def validate_payment(data: dict):
    try:
        return Payment(**data), []
    except ValidationError as exc:
        return None, sorted(".".join(str(p) for p in e["loc"]) for e in exc.errors())
