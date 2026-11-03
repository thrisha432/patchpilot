from app.catalog.models import Book, Ebook


def rename(book: Book, title: str) -> Book:
    return book.model_copy(update={"title": title})


def export(book: Book) -> dict:
    return book.model_dump(exclude_none=True)


def from_record(record) -> Ebook:
    return Ebook.model_validate(record)
