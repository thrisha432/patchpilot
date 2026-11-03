from app.audit import AuditLog
from app.service import audit_snapshot, place

RAW = {"id": "o9", "lines": []}


def test_audit_untouched():
    place(RAW)
    snap = audit_snapshot()
    assert snap["count"] == len(snap["entries"]) and "placed o9" in snap["entries"]
    assert AuditLog(["x"]).copy().dict() == {"entries": ["x"], "count": 1}


def test_empty_order_total():
    assert place(RAW).total == 0.0
