from pydantic import BaseSettings


class Settings(BaseSettings):
    page_size: int = 2
    currency: str = "EUR"

    class Config:
        env_prefix = "INV_"
