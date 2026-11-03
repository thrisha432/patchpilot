from app.metrics import numeric_total, parse_csv_row


def test_numeric_strings_become_ints():
    rows = ["cpu, 42", "mem, 58", "disk, n/a"]
    assert numeric_total([parse_csv_row(r) for r in rows]) == 100
