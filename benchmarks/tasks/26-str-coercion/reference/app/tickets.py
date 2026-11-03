from typing import List

from pydantic import BaseModel, ConfigDict


class Ticket(BaseModel):
    ticket_id: str
    title: str
    assignee_id: str

    model_config = ConfigDict(str_strip_whitespace=True, coerce_numbers_to_str=True)


def from_db_rows(rows: List[tuple]) -> List[Ticket]:
    # The database driver returns integer primary keys.
    return [Ticket(ticket_id=r[0], title=r[1], assignee_id=r[2]) for r in rows]


def by_assignee(tickets: List[Ticket], assignee: str) -> List[str]:
    return [t.ticket_id for t in tickets if t.assignee_id == assignee]
