"""Path extremes calculation for exit simulation.

Computes per-bar return, MFE, and MAE for bars 1-72 after entry.
This is raw price path data, completely SL-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING


from models import TrendDirection
from .config import OUTCOME_WINDOW_BARS

if TYPE_CHECKING:
    from .candle_store import CandleStore


@dataclass
class PathExtremeRow:
    """Single bar's path extreme data."""
    bar_index: int                  # 1 to 72
    return_atr_at_bar: float        # Signed return at bar close
    mfe_atr_to_here: float          # Max favorable excursion up to this bar
    mae_atr_to_here: float          # Max adverse excursion up to this bar (negative)
    mfe_atr_high_low: Optional[float] = None  # Intrabar MFE using high/low
    mae_atr_high_low: Optional[float] = None  # Intrabar MAE using high/low


class PathExtremesCalculator:
    """Computes per-bar return/MFE/MAE for bars 1-72."""
    
    def __init__(
        self,
        candle_store: "CandleStore",
        entry_candle_idx: int,
        entry_price: float,
        atr_at_entry: float,
        direction: TrendDirection,
    ):
        self._store = candle_store
        self._entry_idx = entry_candle_idx
        self._entry_price = entry_price
        self._atr = atr_at_entry
        self._is_long = direction == TrendDirection.BULLISH
    
    def compute(self) -> List[PathExtremeRow]:
        """Compute path extremes for bars 1-72.
        
        Returns:
            List of PathExtremeRow for each bar (up to 72)
        """
        if self._atr <= 0:
            return []
        
        # Get future candles after entry
        candles_1h = self._store.get_1h_candles()
        max_idx = len(candles_1h.candles) - 1
        
        results = []
        running_mfe = float('-inf')
        running_mae = float('inf')
        running_mfe_hl = float('-inf')
        running_mae_hl = float('inf')
        
        for bar_idx in range(1, OUTCOME_WINDOW_BARS + 1):
            candle_idx = self._entry_idx + bar_idx
            if candle_idx > max_idx:
                break
            
            candle = candles_1h.get_candle_at_index(candle_idx)
            if candle is None:
                break
            
            close = float(candle["close"])
            high = float(candle["high"])
            low = float(candle["low"])
            
            # Calculate signed return at bar close
            if self._is_long:
                return_atr = (close - self._entry_price) / self._atr
                # Intrabar extremes
                intrabar_mfe = (high - self._entry_price) / self._atr
                intrabar_mae = (low - self._entry_price) / self._atr
            else:
                return_atr = (self._entry_price - close) / self._atr
                # Intrabar extremes (inverted for bearish)
                intrabar_mfe = (self._entry_price - low) / self._atr
                intrabar_mae = (self._entry_price - high) / self._atr
            
            # Update running MFE/MAE (using close prices)
            running_mfe = max(running_mfe, return_atr)
            running_mae = min(running_mae, return_atr)
            
            # Update running MFE/MAE using high/low (intrabar)
            running_mfe_hl = max(running_mfe_hl, intrabar_mfe)
            running_mae_hl = min(running_mae_hl, intrabar_mae)
            
            results.append(PathExtremeRow(
                bar_index=bar_idx,
                return_atr_at_bar=return_atr,
                mfe_atr_to_here=running_mfe,
                mae_atr_to_here=running_mae,
                mfe_atr_high_low=running_mfe_hl,
                mae_atr_high_low=running_mae_hl,
            ))
        
        return results


def persist_path_extremes(signal_id: int, rows: List[PathExtremeRow]) -> None:
    """Persist path extremes to database."""
    from database.executor import DBExecutor
    from .replay_queries import INSERT_SIGNAL_PATH_EXTREME
    
    if not rows:
        return
    
    def _persist(cursor):
        for row in rows:
            cursor.execute(
                INSERT_SIGNAL_PATH_EXTREME,
                (
                    signal_id,
                    row.bar_index,
                    row.return_atr_at_bar,
                    row.mfe_atr_to_here,
                    row.mae_atr_to_here,
                    row.mfe_atr_high_low,
                    row.mae_atr_high_low,
                ),
            )
    
    DBExecutor.execute_transaction(_persist, context="persist_path_extremes")
