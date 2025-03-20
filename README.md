# 7TV Emote API

A FastAPI-based service for searching, downloading, and storing 7TV emotes in Azure Blob Storage.

### Features

- Search emotes from 7TV and store them in Azure Blob Storage
- Retrieve trending emotes with support for different time periods (daily, weekly, monthly)
- Direct access to stored emotes in Azure Storage
- Redis-based caching for improved performance and reduced API requests
- Rate limiting to prevent abuse
- Pagination support for all endpoints
