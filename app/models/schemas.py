from typing import List, Optional
from pydantic import BaseModel, Field
from enum import Enum

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
