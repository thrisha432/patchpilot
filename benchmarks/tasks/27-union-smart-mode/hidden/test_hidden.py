from app.metrics import Metric, parse_csv_row


def test_label_kept():
    assert parse_csv_row("disk, n/a").value == "n/a"


def test_ints_stay_ints():
    assert Metric(name="x", value=3).value == 3
