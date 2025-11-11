"""Shared response models for the public API."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class TrendEntry(BaseModel):
    symbol: str
    timeframe: str
    trend: str
    high: float = Field(..., description="Highest price in the current trend window")
    low: float = Field(..., description="Lowest price in the current trend window")
    last_updated: datetime


class TrendResponse(BaseModel):
    __root__: List[TrendEntry]


class AreaOfInterest(BaseModel):
    lower_bound: Optional[float]
    upper_bound: Optional[float]


class AreaOfInterestResponse(BaseModel):
    symbol: str
    timeframe: str
    low: Optional[float]
    high: Optional[float]
    aois: List[AreaOfInterest]
