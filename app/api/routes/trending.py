from fastapi import APIRouter, Request, Query
from app.models.schemas import SearchResponse, TrendingPeriod
from app.services.seventv import fetch_7tv_trending_emotes, process_emotes_batch
from app.services.cache import get_trending_cache_key, get_from_cache, save_to_cache
from app.middleware import limiter
from app.config import settings
import time
import aiohttp
import asyncio

router = APIRouter(
    prefix="/api/trending",
    tags=["trending"]
)

@router.get("/emotes", response_model=SearchResponse)
@limiter.limit("100/15minute")
async def trending_emotes(
    request: Request, 
    period: TrendingPeriod = Query(TrendingPeriod.weekly, description="Trending period"),
    limit: int = Query(20, ge=1, le=100, description="Number of emotes per page"),
    page: int = Query(1, ge=1, description="Page number"),
    animated_only: bool = Query(False, description="Only fetch animated emotes")
):
    """
    Get trending emotes from 7TV with pagination support.
    """
    start_time = time.time()
    
    fetch_limit = page * limit
    if fetch_limit > 300:
        fetch_limit = 300  # Cap for 7TV limits
    
    # Check cache (async)
    cache_key = get_trending_cache_key(period, limit, animated_only, page)
    
    cached_data = await get_from_cache(cache_key)
    if cached_data:
        cached_data["processingTime"] = time.time() - start_time
        cached_data["cached"] = True
        return SearchResponse(**cached_data)
    
    # Fetch trending emotes (async)
    async with aiohttp.ClientSession() as session:
        trending_emotes = await fetch_7tv_trending_emotes(period, fetch_limit, animated_only, session)
    
    if not trending_emotes:
        response_data = {
            "success": True,
            "totalFound": 0,
            "emotes": [],
            "message": f"No trending emotes found for period: {period}",
            "processingTime": time.time() - start_time,
            "page": page,
            "totalPages": 0,
            "resultsPerPage": limit
        }
        await save_to_cache(cache_key, response_data, ttl=settings.TRENDING_CACHE_TTL)
        return SearchResponse(**response_data)
    
    # Pagination on fetched emotes
    total_found = len(trending_emotes)
    total_pages = (total_found + limit - 1) // limit
    
    start_idx = (page - 1) * limit
    end_idx = min(start_idx + limit, total_found)
    page_emotes = trending_emotes[start_idx:end_idx]
    
    # Process (async)
    processed_emotes = await process_emotes_batch(page_emotes, "trending_emotes")
    
    response_data = {
        "success": True,
        "totalFound": total_found,
        "emotes": processed_emotes,
        "processingTime": time.time() - start_time,
        "page": page,
        "totalPages": total_pages,
        "resultsPerPage": limit,
        "hasNextPage": page < total_pages
    }
    
    await save_to_cache(cache_key, response_data, ttl=settings.TRENDING_CACHE_TTL)
    
    return SearchResponse(**response_data)