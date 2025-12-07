from __future__ import annotations

from datetime import datetime, timedelta, timezone
from importlib import util
from typing import Any, Iterable, List, Mapping, Sequence

if util.find_spec("pandas") is not None:  # Optional dependency for dataframe callers
    import pandas as pd
else:  # pragma: no cover - fallback when pandas is absent
    pd = None  # type: ignore

from models.market import Candle


_TIMEFRAME_DURATIONS: Mapping[str, timedelta] = {
    "1H": timedelta(hours=1),
    "4H": timedelta(hours=4),
}


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


def last_expected_close_time(timeframe: str, *, now: datetime | None = None) -> datetime:
    """Return the expected close timestamp for the most recent completed candle."""

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if timeframe == "1W":
        start_of_day = datetime(current.year, current.month, current.day, tzinfo=timezone.utc)
        return start_of_day - timedelta(days=current.weekday())

    if timeframe == "1D":
        return datetime(current.year, current.month, current.day, tzinfo=timezone.utc)

    duration = _TIMEFRAME_DURATIONS.get(timeframe)
    if duration is None:
        raise KeyError(f"Unsupported timeframe {timeframe!r} for candle closing logic")

    seconds = duration.total_seconds()
    floored_seconds = current.timestamp() - (current.timestamp() % seconds)
    return datetime.fromtimestamp(floored_seconds, tz=timezone.utc)


def trim_to_closed_candles(
    df: "pd.DataFrame", timeframe: str, *, now: datetime | None = None
) -> "pd.DataFrame":
    """Drop candles that extend beyond the last expected close time for ``timeframe``."""

    if pd is None:
        raise ImportError("pandas is required to trim candles")

    cutoff = last_expected_close_time(timeframe, now=now)
    cutoff_value = cutoff if df["time"].dt.tz is not None else cutoff.replace(tzinfo=None)
    return df[df["time"] < cutoff_value]
