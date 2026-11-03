from app.tickets import by_assignee, from_db_rows


def test_rows_with_integer_ids():
    tickets = from_db_rows([(101, " Fix login ", 7), (102, "Add SSO", 8), (103, "Docs", 7)])
    assert tickets[0].ticket_id == "101" and tickets[0].title == "Fix login"
    assert by_assignee(tickets, "7") == ["101", "103"]
