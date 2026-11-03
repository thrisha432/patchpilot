from app.settings import load_settings


def test_custom_env_name(monkeypatch):
    monkeypatch.setenv("INVENTORY_DB_URL", "postgresql://db/inv")
    assert load_settings().database_url == "postgresql://db/inv"
