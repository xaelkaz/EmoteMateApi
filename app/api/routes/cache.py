from fastapi import APIRouter, Request
from app.services.cache import redis_client
from app.middleware import limiter

router = APIRouter(
    prefix="/api/cache",
    tags=["cache"]
)

@router.get("/status")
@limiter.limit("20/minute")
async def cache_status(request: Request):
    """Get current cache status"""
    try:
        # Get Redis info
        info = redis_client.info()
        keys_count = redis_client.dbsize()
        
        # Get counts for different key types
        emote_search_keys = len(redis_client.keys("emote_search:*"))
        trending_keys = len(redis_client.keys("trending:*"))
        
        return {
            "status": "connected",
            "totalKeys": keys_count,
            "emoteSearchKeys": emote_search_keys,
            "trendingKeys": trending_keys,
            "usedMemory": f"{info['used_memory_human']}",
            "hitRatio": info.get('keyspace_hits', 0) / (info.get('keyspace_hits', 0) + info.get('keyspace_misses', 1)) * 100 if info.get('keyspace_hits', 0) > 0 else 0
        }
    except redis.RedisError as e:
        return {
            "status": "error",
            "message": str(e)
        }

@router.post("/clear")
@limiter.limit("5/minute")
async def clear_cache(request: Request, cache_type: str = "all"):
    """
    Clear cache in Redis
    
    cache_type options:
    - all: Clear all caches
    - search: Clear only search caches
    - trending: Clear only trending caches
    """
    try:
        pattern = None
        if cache_type == "all":
            pattern = "emote_search:*|trending:*"
        elif cache_type == "search":
            pattern = "emote_search:*"
        elif cache_type == "trending":
            pattern = "trending:*"
        else:
            return {
                "success": False,
                "message": "Invalid cache_type. Options are: all, search, trending"
            }
        
        # Find all keys matching the pattern
        all_keys = []
        for p in pattern.split("|"):
            all_keys.extend(redis_client.keys(p))
        
        # Delete the keys if any exist
        if all_keys:
            redis_client.delete(*all_keys)
        
        return {
            "success": True,
            "message": f"Cache cleared. {len(all_keys)} entries removed.",
            "type": cache_type
        }
    except redis.RedisError as e:
        return {
            "success": False,
            "message": f"Error clearing cache: {str(e)}"
        }
