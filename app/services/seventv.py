import requests
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from app.services.storage import upload_to_azure_blob

def fetch_7tv_emotes_api(query, limit=100, animated_only=False):
    """Fetch emotes from 7TV's API by search term."""
    api_url = "https://7tv.io/v3/gql"
    
    gql_query = """
    query EmoteSearch($query: String!, $limit: Int, $filter: EmoteSearchFilter) {
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
        "defaultSetId": "",
        "isDefaultSetSet": False,
        "query": query,
        "page": 1,
        "perPage": limit,
        "limit": limit,
        "sortBy": "TOP_ALL_TIME",
        "filter": {
            "exact_match": False,
            "case_sensitive": False,
            "animated": animated_only if animated_only else None
        }
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
            logging.error(f"Failed to download {emote['name']}: HTTP {response.status_code}")
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
        logging.error(f"Error processing emote {emote.get('name', 'Unknown')}: {e}")
        return None

def process_emotes_batch(emotes, folder="emote_api"):
    """Process a batch of emotes in parallel"""
    processed_emotes = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda e: process_emote(e, folder), emotes))
        processed_emotes = [result for result in results if result]
    return processed_emotes
