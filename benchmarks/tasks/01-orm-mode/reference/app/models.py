from typing import List

from pydantic import BaseModel, ConfigDict


class UserRow:
    """Stands in for an ORM row object (attribute access, not a dict)."""

    def __init__(self, id, name, email, roles):
        self.id = id
        self.name = name
        self.email = email
        self.roles = roles


class User(BaseModel):
    id: int
    name: str
    email: str
    roles: List[str] = []

    model_config = ConfigDict(from_attributes=True)


def user_from_row(row: UserRow) -> User:
    return User.model_validate(row)
