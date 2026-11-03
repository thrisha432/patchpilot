from typing import Optional

from app.core.base import Entity


class Book(Entity):
    title: str
    author: str
    isbn: Optional[str] = None


class Ebook(Book):
    file_size_kb: int
