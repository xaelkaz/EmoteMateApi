import os
import time
import asyncio
import uvloop
from fastapi import FastAPI, Request
from datetime import datetime
import logging

from app.config import settings
from app.middleware import setup_middleware
from app.api.routes import emotes, trending, storage, cache
from app.services.cache import init_redis, redis_client
from app.services.storage import init_azure_storage

# Use uvloop for faster asyncio
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Create FastAPI app
app = FastAPI(
    title=settings.API_TITLE,
    description=settings.API_DESCRIPTION,
    version=settings.API_VERSION
)

# Setup middleware
setup_middleware(app)

# Include routers
app.include_router(emotes.router)
app.include_router(trending.router)
app.include_router(storage.router)
app.include_router(cache.router)

@app.on_event("startup")
async def startup_event():
    await init_redis()
    await init_azure_storage()

@app.get("/")
async def root():
    return {
        "message": "Welcome to the 7TV Emote API", 
        "endpoints": {
            "search": "/api/search-emotes",
            "trending_emotes": "/api/trending/emotes",
            "storage_trending": "/api/storage/trending-emotes",
            "storage_emotes": "/api/storage/emote-api",
            "cache_status": "/api/cache/status",
            "clear_cache": "/api/cache/clear",
            "health": "/health"
        },
        "documentation": "/docs"
    }

@app.get("/health")
async def health_check():
    redis_status = "connected"
    try:
        await redis_client.ping()
    except:
        redis_status = "disconnected"
        
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "redis": redis_status
    }

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)