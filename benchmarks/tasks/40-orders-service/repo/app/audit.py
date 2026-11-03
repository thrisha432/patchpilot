class AuditLog:
    """Append-only log. Its copy()/dict() are plain Python, unrelated to Pydantic."""

    def __init__(self, entries=None):
        self.entries = list(entries or [])

    def add(self, entry: str) -> None:
        self.entries.append(entry)

    def copy(self):
        return AuditLog(self.entries)

    def dict(self):
        return {"entries": list(self.entries), "count": len(self.entries)}
