from fastapi import APIRouter, HTTPException, Request, Query
from app.models.schemas import SearchResponse, SearchRequest
from app.services.seventv import fetch_7tv_emotes_api, process_emotes_batch
from app.services.cache import get_cache_key, get_from_cache, save_to_cache
from app.middleware import limiter
import time
import aiohttp
import asyncio

router = APIRouter(
    prefix="/api",
    tags=["emotes"]
)

@router.post("/search-emotes", response_model=SearchResponse)
@limiter.limit("100/15minute")
async def search_emotes(request: Request, search_request: SearchRequest):
    """
    Search for emotes on 7TV, download them, and store in Azure.
    Returns a list of emotes with their file names and URLs.
    """
    start_time = time.time()
    
    if not search_request.query:
        raise HTTPException(status_code=400, detail="Query parameter is required")
    
    # Check cache first (async)
    cache_key = get_cache_key(
        search_request.query, 
        search_request.limit, 
        search_request.animated_only,
        search_request.page
    )
    
    cached_data = await get_from_cache(cache_key)
    if cached_data:
        cached_data["processingTime"] = time.time() - start_time
        cached_data["cached"] = True
        return SearchResponse(**cached_data)
    
    # For pagination, adjust fetch (assuming 7TV supports page in variables)
    async with aiohttp.ClientSession() as session:
        emotes = await fetch_7tv_emotes_api(
            query=search_request.query, 
            limit=search_request.limit,
            animated_only=search_request.animated_only,
            session=session
        )
    
    if not emotes:
        response_data = {
            "success": True,
            "totalFound": 0,
            "emotes": [],
            "message": "No emotes found for the given query",
            "processingTime": time.time() - start_time,
            "page": search_request.page,
            "totalPages": 1  # Adjust if paginated
        }
        await save_to_cache(cache_key, response_data)
        return SearchResponse(**response_data)
    
    # Process emotes in parallel (async)
    processed_emotes = await process_emotes_batch(emotes, "emote_api")
    
    response_data = {
        "success": True,
        "totalFound": len(emotes),
        "emotes": processed_emotes,
        "processingTime": time.time() - start_time,
        "page": search_request.page,
        "totalPages": 1  # Adjust if needed
    }
    
    # Save to cache (async)
    await save_to_cache(cache_key, response_data)
    
    return SearchResponse(**response_data)