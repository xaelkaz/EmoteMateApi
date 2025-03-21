from app.config import settings
import redis
import json

if settings.REDIS_URL:
    redis_client = redis.from_url(
        settings.REDIS_URL,
        decode_responses=False,
        ssl=True
    )
    print("Connected to Redis using Railway REDIS_URL")
else:
    redis_client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
        decode_responses=False
    )
    print(f"Connected to Redis at {settings.REDIS_HOST}:{settings.REDIS_PORT}")

def get_cache_key(query: str, limit: int, animated_only: bool) -> str:
    """Generate a cache key based on search parameters"""
    return f"emote_search:{query}:{limit}:{animated_only}"

def get_trending_cache_key(period: str, limit: int, animated_only: bool) -> str:
    """Generate a cache key for trending searches"""
    return f"trending:{period}:{limit}:{animated_only}"

def get_from_cache(cache_key: str):
    """Get data from Redis cache if it exists"""
    cached_data = redis_client.get(cache_key)
    if cached_data:
        return json.loads(cached_data)
    return None

def save_to_cache(cache_key: str, data, ttl=settings.CACHE_TTL):
    """Save data to Redis cache with expiration time"""
    redis_client.setex(
        cache_key,
        ttl,
        json.dumps(data)
    )
