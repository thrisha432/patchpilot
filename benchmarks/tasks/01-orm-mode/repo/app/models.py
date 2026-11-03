from typing import List

from pydantic import BaseModel


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

    class Config:
        orm_mode = True


def user_from_row(row: UserRow) -> User:
    return User.from_orm(row)
