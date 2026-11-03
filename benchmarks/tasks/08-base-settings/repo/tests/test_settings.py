from app.settings import load_settings


def test_defaults(monkeypatch):
    for name in ("INVENTORY_DEBUG", "INVENTORY_DB_URL", "INVENTORY_MAX_CONNECTIONS"):
        monkeypatch.delenv(name, raising=False)
    s = load_settings()
    assert (s.app_name, s.debug, s.database_url, s.max_connections) == (
        "inventory", False, "sqlite:///local.db", 10,
    )


def test_env_prefix(monkeypatch):
    monkeypatch.setenv("INVENTORY_DEBUG", "true")
    monkeypatch.setenv("INVENTORY_MAX_CONNECTIONS", "25")
    s = load_settings()
    assert s.debug is True and s.max_connections == 25
