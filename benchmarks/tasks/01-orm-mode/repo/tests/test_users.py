from app.models import UserRow, user_from_row


def test_user_from_row():
    u = user_from_row(UserRow(1, "Ada", "ada@example.com", ["admin"]))
    assert (u.id, u.name, u.email, u.roles) == (1, "Ada", "ada@example.com", ["admin"])
