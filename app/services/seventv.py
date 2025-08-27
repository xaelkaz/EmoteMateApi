import aiohttp
import logging
import os
from app.services.storage import upload_to_azure_blob
import asyncio

async def fetch_7tv_emotes_api(query, limit=100, animated_only=False, session: aiohttp.ClientSession = None):
    """Fetch emotes from 7TV's v4 API by search term (async)."""
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
        async with session.post(api_url, headers=headers, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("data", {}).get("emotes", {}).get("search", {}).get("items", [])
            else:
                logging.error(f"Error from 7TV API: {response.status}")
                logging.error(f"Response: {await response.text()}")
                return []
    except Exception as e:
        logging.error(f"Exception in fetch_7tv_emotes_api: {e}")
        return []

async def fetch_7tv_trending_emotes(period="trending_weekly", limit=20, animated_only=False, session: aiohttp.ClientSession = None):
    """
    Fetch trending emotes from 7TV's API (async).
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
        async with session.post(api_url, headers=headers, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                if "errors" in data:
                    logging.error(f"GraphQL errors: {data['errors']}")
                    return []
                return data.get("data", {}).get("emotes", {}).get("items", [])
            else:
                logging.error(f"Error from 7TV API: {response.status}")
                logging.error(f"Response: {await response.text()}")
                return []
    except Exception as e:
        logging.error(f"Exception in fetch_7tv_trending_emotes: {e}")
        return []

def select_best_image(images):
    """Streamlined image selection with priorities."""
    def filter_animated_webp_scale4(img):
        return img["mime"] == "image/webp" and img.get("scale") == 4 and img.get("frameCount", 1) > 1
    
    def filter_animated_webp(img):
        return img["mime"] == "image/webp" and img.get("frameCount", 1) > 1
    
    def filter_animated(img):
        return img.get("frameCount", 1) > 1
    
    priorities = [
        (filter_animated_webp_scale4, max),
        (filter_animated_webp, max),
        (filter_animated, max),
        (lambda img: True, max)  # Fallback any image
    ]
    for filter_fn, agg_fn in priorities:
        candidates = [img for img in images if filter_fn(img)]
        if candidates:
            return agg_fn(candidates, key=lambda img: img.get("scale", 0))
    return None

async def process_emote(emote, folder="emote_api", session: aiohttp.ClientSession = None):
    """
    Downloads a single emote image from 7TV and uploads it to Azure Blob Storage (async).
    Returns a dictionary with the emote information.
    """
    try:
        images = emote.get("images", [])
        best_image = select_best_image(images)
        
        if not best_image:
            return None
            
        url = best_image["url"]
        async with session.get(url) as response:
            if response.status != 200:
                logging.error(f"Failed to download {emote.get('defaultName', 'unknown')}: HTTP {response.status}")
                return None
            file_data = await response.read()
            
        # Ensure proper extension
        extension = {
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/avif": ".avif",
            "image/png": ".png"
        }.get(best_image["mime"], ".png")
        
        safe_name = "".join([c if c.isalnum() or c in "._- " else "_" for c in emote.get("defaultName", "emote")])
        file_name = f"{safe_name}{extension}"
        blob_name = f"{folder}/{file_name}"
        
        # Upload async with content type
        blob_url = await upload_to_azure_blob(file_data, blob_name, content_type=best_image["mime"])
        
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

async def process_emotes_batch(emotes, folder="emote_api"):
    """Process a batch of emotes in parallel (async)"""
    async with aiohttp.ClientSession() as session:
        tasks = [process_emote(emote, folder, session) for emote in emotes]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        processed_emotes = [r for r in results if r and not isinstance(r, Exception)]
    return processed_emotes