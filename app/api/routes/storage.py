from fastapi import APIRouter, Request, Query
from app.models.schemas import SearchResponse, TrendingPeriod
from app.services.seventv import fetch_7tv_trending_emotes, process_emotes_batch
from app.services.cache import get_trending_cache_key, get_from_cache, save_to_cache
from app.middleware import limiter
from app.config import settings
import time

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
    Returns the most popular emotes based on the specified trending period.
    
    - period: trending_daily, trending_weekly, trending_monthly, or popularity (all-time)
    - limit: Number of emotes per page (max 100)
    - page: Page number (starts at 1)
    - animated_only: Whether to only return animated emotes
    """
    start_time = time.time()
    
    # For 7TV API, we need to fetch enough emotes to reach our pagination target
    # e.g., if page=3 and limit=100, we need to fetch 300 emotes total
    fetch_limit = page * limit
    
    # Check if we hit the 7TV API limits
    if fetch_limit > 300:
        fetch_limit = 300  # 7TV API might have limitations on max results
    
    # Check cache first - we'll cache with pagination parameters
    cache_key = f"trending:{period}:{limit}:{page}:{animated_only}"
    
    cached_data = get_from_cache(cache_key)
    if cached_data:
        # Add processing time to the cached response
        cached_data["processingTime"] = time.time() - start_time
        cached_data["cached"] = True
        return SearchResponse(**cached_data)
    
    # Fetch trending emotes from 7TV API - get enough for the requested page
    trending_emotes = fetch_7tv_trending_emotes(period, fetch_limit, animated_only)
    
    if not trending_emotes:
        response_data = {
            "success": True,
            "totalFound": 0,
            "emotes": [],
            "message": f"No trending emotes found for period: {period}",
            "processingTime": time.time() - start_time,
            "page": page,
            "totalPages": 0
        }
        save_to_cache(cache_key, response_data, ttl=settings.TRENDING_CACHE_TTL)
        return SearchResponse(**response_data)
    
    # Calculate pagination
    total_found = len(trending_emotes)
    total_pages = (total_found + limit - 1) // limit  # Ceiling division
    
    # Extract just the emotes for the current page
    start_idx = (page - 1) * limit
    end_idx = min(start_idx + limit, total_found)
    page_emotes = trending_emotes[start_idx:end_idx]
    
    # Process emotes in parallel
    processed_emotes = process_emotes_batch(page_emotes, "trending_emotes")
    
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
    
    # Save to cache with a shorter TTL for trending data
    save_to_cache(cache_key, response_data, ttl=settings.TRENDING_CACHE_TTL)
    
    return SearchResponse(**response_data)
