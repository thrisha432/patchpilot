from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    app_name: str = "inventory"
    debug: bool = False
    database_url: str = Field("sqlite:///local.db", env="INVENTORY_DB_URL")
    max_connections: int = 10

    class Config:
        env_prefix = "INVENTORY_"


def load_settings() -> Settings:
    return Settings()
