from __future__ import annotations

from importlib import util
from typing import Any, Iterable, List, Mapping, Sequence

if util.find_spec("pandas") is not None:  # Optional dependency for dataframe callers
    import pandas as pd
else:  # pragma: no cover - fallback when pandas is absent
    pd = None  # type: ignore

from models.market import Candle


def to_candle(entry: Candle | Mapping[str, Any]) -> Candle:
    """Convert a mapping or Candle instance into a Candle object."""

    if isinstance(entry, Candle):
        return entry
    if isinstance(entry, Mapping):
        return Candle.from_mapping(entry)
    raise TypeError("Unsupported candle input type")


def prepare_candles(
    candles: "pd.DataFrame | Sequence[Candle | Mapping[str, Any]]",
    *,
    limit: int | None = 15,
    sort_by_time: bool = True,
) -> List[Candle]:
    """Normalize mixed candle inputs into a sliced list of Candle objects."""

    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive when provided")

    if pd is not None and isinstance(candles, pd.DataFrame):
        df = candles
        if sort_by_time and "time" in df.columns:
            df = df.sort_values("time")
        source = df.tail(limit) if limit is not None else df
        raw_entries: Iterable[Mapping[str, Any]] = source.to_dict(orient="records")
    else:
        sequence: Sequence[Candle | Mapping[str, Any]] = list(candles)
        raw_entries = sequence[-limit:] if limit is not None else sequence

    return [to_candle(entry) for entry in raw_entries]


def dataframe_to_candles(
    df: "pd.DataFrame",
    *,
    limit: int | None = None,
    sort_by_time: bool = False,
) -> List[Candle]:
    """Convert a dataframe into Candle objects while optionally preserving order."""

    if pd is None:
        raise ImportError("pandas is required to convert a dataframe to candles")

    return prepare_candles(df, limit=limit, sort_by_time=sort_by_time)
