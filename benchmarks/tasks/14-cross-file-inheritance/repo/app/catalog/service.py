from app.catalog.models import Book, Ebook


def rename(book: Book, title: str) -> Book:
    return book.copy(update={"title": title})


def export(book: Book) -> dict:
    return book.dict(exclude_none=True)


def from_record(record) -> Ebook:
    return Ebook.from_orm(record)
