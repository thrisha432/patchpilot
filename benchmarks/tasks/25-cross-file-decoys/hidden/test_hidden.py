from app.service import export_record, record_json, restore


def test_legacy_record_untouched():
    assert export_record({"name": "x"}) == {"type": "record", "name": "x"}
    assert record_json({"name": "x"}) == '{"name": "x", "type": "record"}'


def test_legacy_snapshot_untouched():
    snap = restore({"payload": {"k": 1}, "version": "3"})
    assert snap.version == 3 and snap.payload == {"k": 1}
