from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "inventory"
    debug: bool = False
    database_url: str = Field("sqlite:///local.db", validation_alias="INVENTORY_DB_URL")
    max_connections: int = 10

    model_config = SettingsConfigDict(env_prefix="INVENTORY_")


def load_settings() -> Settings:
    return Settings()
