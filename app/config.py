import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Redis Configuration
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
    REDIS_DB: int = int(os.getenv("REDIS_DB", 0))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL", None)  # Added for Railway
    CACHE_TTL: int = 60 * 60 * 24  # 24 hours in seconds
    TRENDING_CACHE_TTL: int = 60 * 60 * 6  # 6 hours for trending data

    # Azure Storage Configuration
    AZURE_CONNECTION_STRING: str = os.getenv("AZURE_CONNECTION_STRING", "")
    CONTAINER_NAME: str = os.getenv("CONTAINER_NAME", "")
    
    # API Settings
    API_TITLE: str = "7TV Emote API"
    API_DESCRIPTION: str = "API for searching, downloading, and storing 7TV emotes in Azure Storage"
    API_VERSION: str = "1.0.0"
    
    class Config:
        env_file = ".env"
        
settings = Settings()
