from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    page_size: int = 2
    currency: str = "EUR"

    model_config = SettingsConfigDict(env_prefix="INV_")
