from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_PROJECT_URL: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    API_GATEWAY_URL: str = "http://localhost:8001"
    ADMIN_USERNAME: str = "faltrading"
    ADMIN_EMAIL: str = "faltrade@protonmail.com"
    CHAT_SERVICE_PORT: int = 8003
    DEFAULT_GROUP_NAME: str = "Chat Pubblica"
    DEFAULT_GROUP_DESCRIPTION: str = "Gruppo pubblico per tutti gli utenti"

    @property
    def async_database_url(self) -> str:
        url = self.SUPABASE_URL
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def supabase_realtime_url(self) -> str:
        return self.SUPABASE_PROJECT_URL.replace("https://", "wss://") + "/realtime/v1"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
