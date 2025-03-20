from typing import List, Optional, Literal
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from concurrent.futures import ThreadPoolExecutor
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import redis
import requests
import json
import time
import os
from datetime import datetime
from enum import Enum

# Setup rate limiter and app
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="7TV Emote API",
    description="API for searching, downloading, and storing 7TV emotes in Azure Storage",
    version="1.0.0"
)

# Add rate limiter to app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
CACHE_TTL = 60 * 60 * 24  # 24 hours in seconds
TRENDING_CACHE_TTL = 60 * 60 * 6  # 6 hours for trending data

# Create Redis client
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD,
    decode_responses=False  # Keep binary data as is
)

# Azure Storage Configuration

# Create the BlobServiceClient and get a container client
blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(CONTAINER_NAME)

# -------------------------------
# Pydantic Models for Request/Response
# -------------------------------
class EmoteResponse(BaseModel):
    fileName: str
    url: str
    emoteId: str
    emoteName: str

class SearchResponse(BaseModel):
    success: bool
    totalFound: int
    emotes: List[EmoteResponse]
    message: Optional[str] = None
    cached: bool = False
    processingTime: Optional[float] = None
    page: Optional[int] = 1
    totalPages: Optional[int] = 1
    resultsPerPage: Optional[int] = None
    hasNextPage: Optional[bool] = False

class SearchRequest(BaseModel):
    query: str
    limit: Optional[int] = Field(100, ge=1, le=200)
    animated_only: Optional[bool] = False

class TrendingPeriod(str, Enum):
    daily = "trending_daily"
    weekly = "trending_weekly"
    monthly = "trending_monthly"
    all_time = "popularity"

# -------------------------------
# Redis Cache Functions
# -------------------------------
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

def save_to_cache(cache_key: str, data, ttl=CACHE_TTL):
    """Save data to Redis cache with expiration time"""
    redis_client.setex(
        cache_key,
        ttl,
        json.dumps(data)
    )

# -------------------------------
# Azure Storage Functions
# -------------------------------
def upload_to_azure_blob(file_data, blob_name):
    """
    Upload binary data to Azure Blob Storage if it doesn't already exist.
    Returns the blob URL if successful.
    """
    try:
        blob_client = container_client.get_blob_client(blob=blob_name)
        # Check if the blob already exists
        try:
            blob_client.get_blob_properties()
            print(f"Blob {blob_name} already exists in Azure Blob Storage.")
            return blob_client.url
        except ResourceNotFoundError:
            # Blob does not exist; proceed to upload
            blob_client.upload_blob(file_data)
            print(f"Uploaded {blob_name} to Azure Blob Storage.")
            return blob_client.url
    except Exception as e:
        print(f"Error uploading to Azure Blob: {e}")
        return None

# -------------------------------
# 7TV API Functions
# -------------------------------
def fetch_7tv_emotes_api(query, limit=100, animated_only=False):
    """Fetch emotes from 7TV's API by search term."""
    api_url = "https://7tv.io/v3/gql"
    
    gql_query = """
    query SearchEmotes($query: String!, $limit: Int, $filter: EmoteSearchFilter) {
      emotes(query: $query, limit: $limit, filter: $filter) {
        items {
          id
          name
          animated
          host {
            url
            files {
              name
              format
              width
              height
            }
          }
        }
      }
    }
    """
    
    variables = {
        "query": query,
        "limit": limit,
        "filter": {"case_sensitive": False, "animated": animated_only if animated_only else None}
    }
    
    payload = {
        "query": gql_query,
        "variables": variables
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(api_url, headers=headers, json=payload)
        if response.status_code == 200:
            return response.json().get("data", {}).get("emotes", {}).get("items", [])
        else:
            print(f"Error from 7TV API: {response.status_code}")
            print(f"Response: {response.text}")
            return []
    except Exception as e:
        print(f"Exception in fetch_7tv_emotes_api: {e}")
        return []

def fetch_7tv_trending_emotes(period="trending_weekly", limit=20, animated_only=False):
    """
    Fetch trending emotes from 7TV's API.
    
    Parameters:
    - period: The trending period (trending_daily, trending_weekly, trending_monthly, or popularity)
    - limit: Number of emotes to fetch
    - animated_only: Whether to fetch only animated emotes
    """
    api_url = "https://7tv.io/v3/gql"
    
    gql_query = """
    query GetTrendingEmotes($limit: Int, $filter: EmoteSearchFilter, $period: String!) {
      emotes(query: "", limit: $limit, filter: $filter, sort: { value: $period, order: DESCENDING }) {
        items {
          id
          name
          animated
          host {
            url
            files {
              name
              format
              width
              height
            }
          }
        }
      }
    }
    """
    
    variables = {
        "limit": limit,
        "filter": {"animated": animated_only if animated_only else None},
        "period": period
    }
    
    payload = {
        "query": gql_query,
        "variables": variables
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(api_url, headers=headers, json=payload)
        if response.status_code == 200:
            data = response.json()
            if "errors" in data:
                print(f"GraphQL errors: {data['errors']}")
                return []
            return data.get("data", {}).get("emotes", {}).get("items", [])
        else:
            print(f"Error from 7TV API: {response.status_code}")
            print(f"Response: {response.text}")
            return []
    except Exception as e:
        print(f"Exception in fetch_7tv_trending_emotes: {e}")
        return []

def process_emote(emote, folder="emote_api"):
    """
    Downloads a single emote image from 7TV and uploads it to Azure Blob Storage.
    Returns a dictionary with the emote information.
    
    Parameters:
    - emote: The emote data from 7TV
    - folder: The folder in Azure Storage to save the emote (emote_api or trending_emotes)
    """
    try:
        # Get the emote URL
        base_url = emote["host"]["url"]
        if base_url.startswith('//'):
            base_url = "https:" + base_url
        
        # Find the best file (prefer WEBP or GIF)
        best_file = None
        for file in emote["host"]["files"]:
            if file["format"] in ["WEBP", "GIF"]:
                if best_file is None or file["width"] > best_file["width"]:
                    best_file = file
        
        # Fallback to the first file if no WEBP or GIF is found
        if not best_file and emote["host"]["files"]:
            best_file = emote["host"]["files"][0]
        
        if not best_file:
            return None
        
        # Download the emote
        url = f"{base_url}/{best_file['name']}"
        response = requests.get(url)
        
        if response.status_code != 200:
            print(f"Failed to download {emote['name']}: HTTP {response.status_code}")
            return None
        
        # Create a safe file name
        format_map = {"WEBP": ".webp", "GIF": ".gif", "AVIF": ".avif", "PNG": ".png"}
        extension = format_map.get(best_file["format"], ".png")
        safe_name = "".join([c if c.isalnum() or c in "._- " else "_" for c in emote["name"]])
        file_name = f"{safe_name}{extension}"
        
        # Construct the Azure blob name with specified folder path
        blob_name = f"{folder}/{file_name}"
        
        # Upload to Azure Storage
        blob_url = upload_to_azure_blob(response.content, blob_name)
        
        if not blob_url:
            return None
            
        return {
            "fileName": file_name,
            "url": blob_url,
            "emoteId": emote["id"],
            "emoteName": emote["name"]
        }
        
    except Exception as e:
        print(f"Error processing emote {emote.get('name', 'Unknown')}: {e}")
        return None

# -------------------------------
# API Endpoints
# -------------------------------
@app.post("/api/search-emotes", response_model=SearchResponse)
@limiter.limit("100/15minute")
async def search_emotes(request: Request, search_request: SearchRequest):
    """
    Search for emotes on 7TV, download them, and store in Azure.
    Returns a list of emotes with their file names and URLs.
    """
    start_time = time.time()
    
    if not search_request.query:
        raise HTTPException(status_code=400, detail="Query parameter is required")
    
    # Check cache first
    cache_key = get_cache_key(
        search_request.query, 
        search_request.limit, 
        search_request.animated_only
    )
    
    cached_data = get_from_cache(cache_key)
    if cached_data:
        # Add processing time to the cached response
        cached_data["processingTime"] = time.time() - start_time
        cached_data["cached"] = True
        return SearchResponse(**cached_data)
    
    # Fetch emotes from 7TV API
    emotes = fetch_7tv_emotes_api(
        query=search_request.query, 
        limit=search_request.limit,
        animated_only=search_request.animated_only
    )
    
    if not emotes:
        response_data = {
            "success": True,
            "totalFound": 0,
            "emotes": [],
            "message": "No emotes found for the given query",
            "processingTime": time.time() - start_time
        }
        save_to_cache(cache_key, response_data)
        return SearchResponse(**response_data)
    
    # Process emotes in parallel
    processed_emotes = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda e: process_emote(e, "emote_api"), emotes))
        processed_emotes = [result for result in results if result]
    
    response_data = {
        "success": True,
        "totalFound": len(emotes),
        "emotes": processed_emotes,
        "processingTime": time.time() - start_time
    }
    
    # Save to cache
    save_to_cache(cache_key, response_data)
    
    return SearchResponse(**response_data)


@app.get("/api/trending/emotes", response_model=SearchResponse)
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
        save_to_cache(cache_key, response_data, ttl=TRENDING_CACHE_TTL)
        return SearchResponse(**response_data)
    
    # Calculate pagination
    total_found = len(trending_emotes)
    total_pages = (total_found + limit - 1) // limit  # Ceiling division
    
    # Extract just the emotes for the current page
    start_idx = (page - 1) * limit
    end_idx = min(start_idx + limit, total_found)
    page_emotes = trending_emotes[start_idx:end_idx]
    
    # Process emotes in parallel and save to trending_emotes folder
    processed_emotes = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda e: process_emote(e, "trending_emotes"), page_emotes))
        processed_emotes = [result for result in results if result]
    
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
    save_to_cache(cache_key, response_data, ttl=TRENDING_CACHE_TTL)
    
    return SearchResponse(**response_data)

@app.get("/api/storage/trending-emotes", response_model=SearchResponse)
@limiter.limit("50/15minute")
async def get_trending_emotes_from_storage(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Number of emotes per page")
):
    """
    Get trending emotes directly from Azure Storage.
    This endpoint bypasses the 7TV API and retrieves files directly from the 'trending_emotes' folder.
    
    - limit: Number of emotes per page (max 100)
    - page: Page number (starts at 1)
    """
    start_time = time.time()
    
    try:
        # List all blobs in the trending_emotes folder
        prefix = "trending_emotes/"
        blobs = container_client.list_blobs(name_starts_with=prefix)
        
        # Convert to list to allow sorting and multiple iterations
        blob_list = list(blobs)
        
        # Sort by name to ensure consistent ordering
        blob_list.sort(key=lambda b: b.name)
        
        if not blob_list:
            response_data = {
                "success": True,
                "totalFound": 0,
                "emotes": [],
                "message": "No trending emotes found in storage",
                "processingTime": time.time() - start_time,
                "page": page,
                "totalPages": 0,
                "resultsPerPage": limit
            }
            return SearchResponse(**response_data)
        
        # Calculate pagination
        total_found = len(blob_list)
        total_pages = (total_found + limit - 1) // limit  # Ceiling division
        
        # Extract just the blobs for the current page
        start_idx = (page - 1) * limit
        end_idx = min(start_idx + limit, total_found)
        
        # Check if requested page is valid
        if start_idx >= total_found:
            response_data = {
                "success": False,
                "totalFound": total_found,
                "emotes": [],
                "message": f"Page {page} exceeds available pages (total: {total_pages})",
                "processingTime": time.time() - start_time,
                "page": page,
                "totalPages": total_pages,
                "resultsPerPage": limit,
                "hasNextPage": False
            }
            return SearchResponse(**response_data)
        
        page_blobs = blob_list[start_idx:end_idx]
        
        # Process each blob into the required format
        processed_emotes = []
        for blob in page_blobs:
            # Extract filename from the blob name
            file_name = blob.name.replace(prefix, "")
            
            # Skip empty filenames or folders
            if not file_name or file_name.endswith('/'):
                continue
                
            # Get the blob URL
            blob_client = container_client.get_blob_client(blob.name)
            blob_url = blob_client.url
            
            # Try to extract emote name from filename (remove extension)
            emote_name = os.path.splitext(file_name)[0]
            
            # Create a pseudo-ID if we don't have the actual 7TV ID
            emote_id = f"storage_{hash(blob.name) % 10000000}"  # Simple hash for ID
            
            processed_emotes.append({
                "fileName": file_name,
                "url": blob_url,
                "emoteId": emote_id,
                "emoteName": emote_name
            })
        
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
        
        return SearchResponse(**response_data)
        
    except Exception as e:
        return SearchResponse(
            success=False,
            totalFound=0,
            emotes=[],
            message=f"Error accessing Azure Storage: {str(e)}",
            processingTime=time.time() - start_time,
            page=page,
            totalPages=0,
            resultsPerPage=limit,
            hasNextPage=False
        )

@app.get("/api/storage/emote-api", response_model=SearchResponse)
@limiter.limit("50/15minute")
async def get_emotes_from_storage(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Number of emotes per page")
):
    """
    Get emotes directly from Azure Storage.
    This endpoint bypasses the 7TV API and retrieves files directly from the 'emote_api' folder.
    
    - limit: Number of emotes per page (max 100)
    - page: Page number (starts at 1)
    """
    start_time = time.time()
    
    try:
        # List all blobs in the emote_api folder
        prefix = "emote_api/"
        blobs = container_client.list_blobs(name_starts_with=prefix)
        
        # Convert to list to allow sorting and multiple iterations
        blob_list = list(blobs)
        
        # Sort by name to ensure consistent ordering
        blob_list.sort(key=lambda b: b.name)
        
        if not blob_list:
            response_data = {
                "success": True,
                "totalFound": 0,
                "emotes": [],
                "message": "No emotes found in storage",
                "processingTime": time.time() - start_time,
                "page": page,
                "totalPages": 0,
                "resultsPerPage": limit
            }
            return SearchResponse(**response_data)
        
        # Calculate pagination
        total_found = len(blob_list)
        total_pages = (total_found + limit - 1) // limit  # Ceiling division
        
        # Extract just the blobs for the current page
        start_idx = (page - 1) * limit
        end_idx = min(start_idx + limit, total_found)
        
        # Check if requested page is valid
        if start_idx >= total_found:
            response_data = {
                "success": False,
                "totalFound": total_found,
                "emotes": [],
                "message": f"Page {page} exceeds available pages (total: {total_pages})",
                "processingTime": time.time() - start_time,
                "page": page,
                "totalPages": total_pages,
                "resultsPerPage": limit,
                "hasNextPage": False
            }
            return SearchResponse(**response_data)
        
        page_blobs = blob_list[start_idx:end_idx]
        
        # Process each blob into the required format
        processed_emotes = []
        for blob in page_blobs:
            # Extract filename from the blob name
            file_name = blob.name.replace(prefix, "")
            
            # Skip empty filenames or folders
            if not file_name or file_name.endswith('/'):
                continue
                
            # Get the blob URL
            blob_client = container_client.get_blob_client(blob.name)
            blob_url = blob_client.url
            
            # Try to extract emote name from filename (remove extension)
            emote_name = os.path.splitext(file_name)[0]
            
            # Create a pseudo-ID if we don't have the actual 7TV ID
            emote_id = f"storage_{hash(blob.name) % 10000000}"  # Simple hash for ID
            
            processed_emotes.append({
                "fileName": file_name,
                "url": blob_url,
                "emoteId": emote_id,
                "emoteName": emote_name
            })
        
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
        
        return SearchResponse(**response_data)
        
    except Exception as e:
        return SearchResponse(
            success=False,
            totalFound=0,
            emotes=[],
            message=f"Error accessing Azure Storage: {str(e)}",
            processingTime=time.time() - start_time,
            page=page,
            totalPages=0,
            resultsPerPage=limit,
            hasNextPage=False
        )

@app.get("/api/cache/status")
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

@app.post("/api/cache/clear")
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

@app.get("/")
@limiter.limit("200/minute")
async def root(request: Request):
    return {
        "message": "Welcome to the 7TV Emote API", 
        "endpoints": {
            "search": "/api/search-emotes",
            "trending_emotes": "/api/trending/emotes",
            "trending_searches": "/api/trending/searches",
            "cache_status": "/api/cache/status",
            "clear_cache": "/api/cache/clear",
            "health": "/health"
        },
        "documentation": "/docs"
    }

@app.get("/health")
@limiter.limit("1000/hour")
async def health_check(request: Request):
    redis_status = "connected"
    try:
        redis_client.ping()
    except:
        redis_status = "disconnected"
        
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "redis": redis_status
    }

# Custom exception handler for rate limiting
@app.exception_handler(RateLimitExceeded)
async def custom_rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=429,
        content={"error": "Too many requests from this IP, please try again later"}
    )

# Start the server with: uvicorn main:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
