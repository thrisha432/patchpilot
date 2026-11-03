from datetime import datetime
from types import SimpleNamespace

from app.catalog.models import Book
from app.catalog.service import export, from_record, rename

NOW = datetime(2024, 1, 1, 12, 0)


def test_export_skips_none():
    book = Book(id=1, created_at=NOW, title="Dune", author="Herbert")
    assert export(book) == {"id": 1, "created_at": NOW, "title": "Dune", "author": "Herbert"}


def test_rename():
    book = Book(id=1, created_at=NOW, title="Dune", author="Herbert")
    assert rename(book, "Dune Messiah").title == "Dune Messiah"


def test_from_record():
    rec = SimpleNamespace(id=2, created_at=NOW, title="T", author="A", isbn=None, file_size_kb=120)
    assert from_record(rec).file_size_kb == 120
