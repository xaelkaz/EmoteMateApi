import requests
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from app.services.storage import upload_to_azure_blob

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
        "query": query,
        "tags": [],
        "sortBy": "TRENDING_MONTHLY",
        "filters": {
            "animated": animated_only if animated_only else False
        },
        "page": 1,
        "perPage": limit,
        "isDefaultSetSet": False,
        "defaultSetId": ""
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
    """
    try:
        # Find the best image (prefer webp, then gif, then png, then avif, largest scale)
        best_image = None
        preferred_mimes = ["image/webp", "image/gif", "image/png", "image/avif"]
        for mime in preferred_mimes:
            images = [img for img in emote.get("images", []) if img["mime"] == mime]
            if images:
                # Pick the largest scale
                best_image = max(images, key=lambda img: img.get("scale", 1))
                break
        # Fallback to any image
        if not best_image and emote.get("images"):
            best_image = emote["images"][0]
        if not best_image:
            return None
        url = best_image["url"]
        response = requests.get(url)
        if response.status_code != 200:
            logging.error(f"Failed to download {emote.get('defaultName', 'unknown')}: HTTP {response.status_code}")
            return None
        # Create a safe file name
        extension = {
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/avif": ".avif",
            "image/png": ".png"
        }.get(best_image["mime"], ".png")
        safe_name = "".join([c if c.isalnum() or c in "._- " else "_" for c in emote.get("defaultName", "emote")])
        file_name = f"{safe_name}{extension}"
        blob_name = f"{folder}/{file_name}"
        blob_url = upload_to_azure_blob(response.content, blob_name)
        if not blob_url:
            return None
        return {
            "fileName": file_name,
            "url": blob_url,
            "emoteId": emote["id"],
            "emoteName": emote.get("defaultName", ""),
            "owner": emote.get("owner", {}).get("mainConnection", {}).get("platformDisplayName", ""),
            "animated": any(img.get("frameCount", 1) > 1 for img in emote.get("images", []))
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
