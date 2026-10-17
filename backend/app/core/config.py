
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL configuration
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "careplus_db"
    db_user: str = "careplus_user"
    db_password: str

    # Authentication configuration
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Frontend URL allowed to access the API
    # Set FRONTEND_ORIGIN in Render to your deployed frontend URL.
    frontend_origin: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
