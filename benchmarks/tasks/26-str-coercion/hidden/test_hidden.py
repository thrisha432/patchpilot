from app.tickets import Ticket, from_db_rows


def test_string_ids_still_work():
    assert from_db_rows([("A-1", "t", "u-9")])[0].assignee_id == "u-9"


def test_direct_construction_with_strings():
    assert Ticket(ticket_id="5", title=" x ", assignee_id="1").title == "x"
