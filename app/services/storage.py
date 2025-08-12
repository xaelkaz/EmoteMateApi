from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError
from app.config import settings
import requests
import logging
import os

# Initialize these as None for lazy loading
blob_service_client = None
container_client = None

def init_azure_storage():
    """Initialize Azure Storage clients only when needed"""
    global blob_service_client, container_client
    
    try:
        azure_conn_string = settings.AZURE_CONNECTION_STRING
        container_name = settings.CONTAINER_NAME
        
        if not azure_conn_string or azure_conn_string == "":
            logging.warning("Azure Storage connection string not properly configured")
            return False
            
        blob_service_client = BlobServiceClient.from_connection_string(azure_conn_string)
        container_client = blob_service_client.get_container_client(container_name)
        logging.info("Azure Storage initialized successfully")
        return True
    except Exception as e:
        logging.error(f"Failed to initialize Azure Storage: {e}")
        return False

def azure_storage_available():
    """Check if Azure Storage is properly configured and available"""
    global blob_service_client, container_client
    
    if blob_service_client is None or container_client is None:
        return init_azure_storage()
    return True

def upload_to_azure_blob(file_data, blob_name, content_type=None):
    """
    Upload binary data to Azure Blob Storage if it doesn't already exist.
    Returns the blob URL if successful, None if Azure Storage is not available.
    
    Parameters:
    - file_data: Binary data to upload
    - blob_name: Name to give the blob in storage
    - content_type: Optional MIME type to set for the blob (ensures proper handling)
    """
    if not azure_storage_available():
        logging.warning("Azure Storage not available, skipping upload")
        return None
        
    try:
        blob_client = container_client.get_blob_client(blob=blob_name)
        # Check if the blob already exists
        try:
            blob_client.get_blob_properties()
            logging.info(f"Blob {blob_name} already exists in Azure Blob Storage.")
            return blob_client.url
        except ResourceNotFoundError:
            # Blob does not exist; proceed to upload
            content_settings = None
            if content_type:
                from azure.storage.blob import ContentSettings
                content_settings = ContentSettings(content_type=content_type)
                
            blob_client.upload_blob(file_data, content_settings=content_settings)
            logging.info(f"Uploaded {blob_name} to Azure Blob Storage with content type: {content_type}")
            return blob_client.url
    except Exception as e:
        logging.error(f"Error uploading to Azure Blob: {e}")
        return None


def get_blob_url_if_exists(blob_name: str):
    """Return blob URL if the blob exists; otherwise None."""
    if not azure_storage_available():
        return None
    try:
        blob_client = container_client.get_blob_client(blob=blob_name)
        blob_client.get_blob_properties()
        return blob_client.url
    except ResourceNotFoundError:
        return None
    except Exception as e:
        logging.error(f"Error checking blob existence for {blob_name}: {e}")
        return None

def list_blobs_with_prefix(prefix: str):
    """List all blobs with the given prefix"""
    if not azure_storage_available():
        logging.warning("Azure Storage not available, returning empty list")
        return []
        
    try:
        blobs = container_client.list_blobs(name_starts_with=prefix)
        return list(blobs)
    except Exception as e:
        logging.error(f"Error listing blobs with prefix {prefix}: {e}")
        return []
