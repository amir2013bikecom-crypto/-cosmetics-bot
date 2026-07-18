from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/cosmetics_db"
    BOT_TOKEN: str = ""
    MINI_APP_URL: str = "https://yourdomain.com"
    DEBUG: bool = True


settings = Settings()
