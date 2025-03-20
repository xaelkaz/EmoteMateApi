from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError
from app.config import settings
import requests
import logging

# Create the BlobServiceClient and get a container client
blob_service_client = BlobServiceClient.from_connection_string(settings.AZURE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(settings.CONTAINER_NAME)

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
            logging.info(f"Blob {blob_name} already exists in Azure Blob Storage.")
            return blob_client.url
        except ResourceNotFoundError:
            # Blob does not exist; proceed to upload
            blob_client.upload_blob(file_data)
            logging.info(f"Uploaded {blob_name} to Azure Blob Storage.")
            return blob_client.url
    except Exception as e:
        logging.error(f"Error uploading to Azure Blob: {e}")
        return None

def list_blobs_with_prefix(prefix: str):
    """List all blobs with the given prefix"""
    try:
        blobs = container_client.list_blobs(name_starts_with=prefix)
        return list(blobs)
    except Exception as e:
        logging.error(f"Error listing blobs with prefix {prefix}: {e}")
        return []
