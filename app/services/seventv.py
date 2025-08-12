import requests
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from app.services.storage import upload_to_azure_blob
from app.services.image_processing import resize_and_pad_webp_bytes

def fetch_7tv_emotes_api(query, limit=100, animated_only=False):
    """Fetch emotes from 7TV's v4 API by search term."""
    api_url = "https://api.7tv.app/v4/gql"

    gql_query = """
    query EmoteSearch($query: String, $tags: [String!]!, $sortBy: SortBy!, $filters: Filters, $page: Int, $perPage: Int!, $isDefaultSetSet: Boolean!, $defaultSetId: Id!) {
      emotes {
        search(
          query: $query
          tags: { tags: $tags, match: ANY }
          sort: { sortBy: $sortBy, order: DESCENDING }
          filters: $filters
          page: $page
          perPage: $perPage
        ) {
          items {
            id
            defaultName
            owner {
              mainConnection {
                platformDisplayName
              }
            }
            images {
              url
              mime
              size
              scale
              width
              frameCount
            }
            ranking(ranking: TRENDING_WEEKLY)
            inEmoteSets(emoteSetIds: [$defaultSetId]) @include(if: $isDefaultSetSet) {
              emoteSetId
              emote {
                id
                alias
              }
            }
          }
          totalCount
          pageCount
        }
      }
    }
    """

    variables = {
        "defaultSetId": "",
        "filters": {
            "animated": animated_only if animated_only else False
        },
        "isDefaultSetSet": False,
        "page": 1,
        "perPage": limit,
        "query": query,
        "sortBy": "TOP_ALL_TIME",
        "tags": [],

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
            return response.json().get("data", {}).get("emotes", {}).get("search", {}).get("items", [])
        else:
            logging.error(f"Error from 7TV API: {response.status_code}")
            logging.error(f"Response: {response.text}")
            return []
    except Exception as e:
        logging.error(f"Exception in fetch_7tv_emotes_api: {e}")
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
                logging.error(f"GraphQL errors: {data['errors']}")
                return []
            return data.get("data", {}).get("emotes", {}).get("items", [])
        else:
            logging.error(f"Error from 7TV API: {response.status_code}")
            logging.error(f"Response: {response.text}")
            return []
    except Exception as e:
        logging.error(f"Exception in fetch_7tv_trending_emotes: {e}")
        return []

def process_emote(emote, folder="emote_api"):
    """
    Downloads a single emote image from 7TV and uploads it to Azure Blob Storage.
    Returns a dictionary with the emote information.
    Updated for v4 API response structure.
    Prioritizes 4x.webp animated images.
    """
    try:
        images = emote.get("images", [])
        # 1. Filter for animated images (frameCount > 1)
        animated_images = [img for img in images if img.get("frameCount", 1) > 1]
        static_images = [img for img in images if img.get("frameCount", 1) <= 1]

        best_image = None
        
        # First priority: Find 4x.webp animated image
        for img in animated_images:
            if img["mime"] == "image/webp" and img.get("scale", 0) == 4:
                best_image = img
                break
                
        # Second priority: Any animated webp with highest scale
        if not best_image and animated_images:
            webp_animated = [img for img in animated_images if img["mime"] == "image/webp"]
            if webp_animated:
                best_image = max(webp_animated, key=lambda img: img.get("scale", 0))
        
        # Third priority: Any animated image with highest scale
        if not best_image and animated_images:
            preferred_animated_mimes = ["image/webp", "image/gif", "image/avif"]
            for mime in preferred_animated_mimes:
                candidates = [img for img in animated_images if img["mime"] == mime]
                if candidates:
                    best_image = max(candidates, key=lambda img: img.get("scale", 0))
                    break
                    
        # Fourth priority: Static images if no animated are available
        if not best_image:
            preferred_static_mimes = ["image/webp", "image/png", "image/avif"]
            for mime in preferred_static_mimes:
                candidates = [img for img in static_images if img["mime"] == mime]
                if candidates:
                    best_image = max(candidates, key=lambda img: img.get("scale", 0))
                    break
                    
        # Final fallback to any image
        if not best_image and images:
            best_image = images[0]
            
        if not best_image:
            return None
            
        url = best_image["url"]
        response = requests.get(url)
        if response.status_code != 200:
            logging.error(f"Failed to download {emote.get('defaultName', 'unknown')}: HTTP {response.status_code}")
            return None
        
        # Process animated webp to 512x512 canvas, preserving animation
        processed_content = response.content
        if best_image.get("mime") == "image/webp" and best_image.get("frameCount", 1) > 1:
            try:
                processed_content = resize_and_pad_webp_bytes(processed_content, size=(512, 512))
            except Exception as processing_error:
                logging.error(f"Failed to resize animated webp for {emote.get('defaultName', 'unknown')}: {processing_error}")
            
        # Ensure we keep the proper extension for the mime type
        extension = {
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/avif": ".avif",
            "image/png": ".png"
        }.get(best_image["mime"], ".png")
        
        safe_name = "".join([c if c.isalnum() or c in "._- " else "_" for c in emote.get("defaultName", "emote")])
        file_name = f"{safe_name}{extension}"
        blob_name = f"{folder}/{file_name}"
        
        # Pass content type to ensure proper MIME type is set in Azure storage
        blob_url = upload_to_azure_blob(processed_content, blob_name, content_type=best_image["mime"])
        
        if not blob_url:
            return None
            
        return {
            "fileName": file_name,
            "url": blob_url,
            "emoteId": emote["id"],
            "emoteName": emote.get("defaultName", ""),
            "owner": emote.get("owner", {}).get("mainConnection", {}).get("platformDisplayName", ""),
            "animated": best_image.get("frameCount", 1) > 1,
            "scale": best_image.get("scale", 1),
            "mime": best_image["mime"]
        }
    except Exception as e:
        logging.error(f"Error processing emote {emote.get('defaultName', 'Unknown')}: {e}")
        return None

def process_emotes_batch(emotes, folder="emote_api"):
    """Process a batch of emotes in parallel"""
    processed_emotes = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda e: process_emote(e, folder), emotes))
        processed_emotes = [result for result in results if result]
    return processed_emotes
