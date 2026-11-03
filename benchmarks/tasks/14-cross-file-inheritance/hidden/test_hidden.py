from datetime import datetime
from types import SimpleNamespace

from app.catalog.service import export, from_record

NOW = datetime(2024, 1, 1)


def test_ebook_export_from_record():
    rec = SimpleNamespace(id=3, created_at=NOW, title="T", author="A", isbn="978", file_size_kb=1)
    assert export(from_record(rec))["isbn"] == "978"
