from fastapi import APIRouter, Request, Query
from app.models.schemas import SearchResponse
from app.services.storage import container_client, azure_storage_available, list_blobs_with_prefix
from app.middleware import limiter
import time
import os

router = APIRouter(
    prefix="/api/storage",
    tags=["storage"]
)

@router.get("/trending-emotes", response_model=SearchResponse)
@limiter.limit("50/15minute")
async def get_trending_emotes_from_storage(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Number of emotes per page")
):
    """
    Get trending emotes directly from Azure Storage.
    """
    start_time = time.time()
    
    # Check if Azure Storage is available (async)
    if not await azure_storage_available():
        return SearchResponse(
            success=False,
            totalFound=0,
            emotes=[],
            message="Azure Storage is not properly configured or unavailable",
            processingTime=time.time() - start_time,
            page=page,
            totalPages=0,
            resultsPerPage=limit,
            hasNextPage=False
        )
    
    try:
        # List all blobs in the trending_emotes folder (async)
        prefix = "trending_emotes/"
        blob_list = await list_blobs_with_prefix(prefix)
        
        # Sort by name
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
        
        # Pagination
        total_found = len(blob_list)
        total_pages = (total_found + limit - 1) // limit
        
        start_idx = (page - 1) * limit
        end_idx = min(start_idx + limit, total_found)
        
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
        
        # Process blobs
        processed_emotes = []
        for blob in page_blobs:
            file_name = blob.name.replace(prefix, "")
            if not file_name or file_name.endswith('/'):
                continue
                
            blob_client = container_client.get_blob_client(blob.name)
            blob_url = blob_client.url  # URL is sync property
            
            emote_name = os.path.splitext(file_name)[0]
            emote_id = f"storage_{hash(blob.name) % 10000000}"
            
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

@router.get("/emote-api", response_model=SearchResponse)
@limiter.limit("50/15minute")
async def get_emotes_from_storage(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Number of emotes per page")
):
    """
    Get emotes directly from Azure Storage.
    """
    start_time = time.time()
    
    if not await azure_storage_available():
        return SearchResponse(
            success=False,
            totalFound=0,
            emotes=[],
            message="Azure Storage is not properly configured or unavailable",
            processingTime=time.time() - start_time,
            page=page,
            totalPages=0,
            resultsPerPage=limit,
            hasNextPage=False
        )
    
    try:
        prefix = "emote_api/"
        blob_list = await list_blobs_with_prefix(prefix)
        
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
        
        total_found = len(blob_list)
        total_pages = (total_found + limit - 1) // limit
        
        start_idx = (page - 1) * limit
        end_idx = min(start_idx + limit, total_found)
        
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
        
        processed_emotes = []
        for blob in page_blobs:
            file_name = blob.name.replace(prefix, "")
            if not file_name or file_name.endswith('/'):
                continue
                
            blob_client = container_client.get_blob_client(blob.name)
            blob_url = blob_client.url
            
            emote_name = os.path.splitext(file_name)[0]
            emote_id = f"storage_{hash(blob.name) % 10000000}"
            
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