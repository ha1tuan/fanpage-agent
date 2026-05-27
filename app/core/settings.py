from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    APP_NAME: str = "Career Agent API"
    DEBUG: bool = False
    
    LLM_PROVIDER: str
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:latest"
    EXA_API_KEY: str

    DATABASE_URL: str
    REDIS_URL: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    IMAGE_OUTPUT_DIR: str = "assets/images"
    VIDEO_OUTPUT_DIR: str = "assets/videos"

    KLING_SECRET_KEY: str
    KLING_ACCESS_KEY: str

    REPLICATE_API_TOKEN: str = ""

    # Telegram (Phase 5)
    TELEGRAM_BOT_TOKEN: str 
    TELEGRAM_CHAT_ID: str 

    #FB
    META_APP_ID: str
    META_APP_SECRET: str
    META_PAGE_ID: str
    META_PAGE_ACCESS_TOKEN: str

@lru_cache()
def get_settings() -> Settings:
    return Settings()
