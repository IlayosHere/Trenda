"""Exit simulation for multiple SL/TP configurations.

Simulates exits for all SL model × R multiple combinations.
Uses path extremes to determine SL/TP hits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING

from .config import SL_MODELS, RR_MULTIPLES, OUTCOME_WINDOW_BARS
from .sl_geometry import SLGeometryData
from .path_extremes import PathExtremeRow

if TYPE_CHECKING:
    pass


@dataclass
class ExitSimulationRow:
    """Exit simulation result for one SL model × R multiple combination."""
    
    sl_model: str
    rr_multiple: float
    sl_atr: float
    tp_atr: float
    exit_reason: str              # SL, TP, TIMEOUT
    exit_bar: int
    return_atr: float
    return_r: float
    mfe_atr: float
    mae_atr: float
    bars_to_sl_hit: Optional[int]
    bars_to_tp_hit: Optional[int]
    is_bad_pre48: bool


class ExitSimulator:
    """Simulates exits for all SL model × R multiple combinations."""
    
    def __init__(
        self,
        geometry: SLGeometryData,
        path_extremes: List[PathExtremeRow],
    ):
        self._geometry = geometry
        self._path = path_extremes
    
    def simulate_all(self) -> List[ExitSimulationRow]:
        """Simulate exits for all SL × R combinations.
        
        Returns:
            List of ExitSimulationRow (9 SL models × 5 R multiples = 45 rows)
        """
        results = []
        
        for sl_model in SL_MODELS:
            sl_atr = self._resolve_sl(sl_model)
            if sl_atr is None or sl_atr <= 0:
                continue
            
            for rr_multiple in RR_MULTIPLES:
                tp_atr = sl_atr * rr_multiple
                result = self._simulate_one(sl_model, rr_multiple, sl_atr, tp_atr)
                results.append(result)
        
        return results
    
    def _resolve_sl(self, sl_model: str) -> Optional[float]:
        """Resolve SL distance in ATR units for a given model.
        
        Args:
            sl_model: The SL model name
            
        Returns:
            SL distance in ATR units, or None if cannot resolve
            
        Note:
            For PLUS_X models, the buffer pushes SL further from entry.
            Since sl_atr is always a positive distance, adding the buffer
            means the SL is further away regardless of direction.
        """
        # Fixed ATR-based SL distances
        if sl_model == "SL_ATR_0_1":
            return 0.1
        elif sl_model == "SL_ATR_0_2":
            return 0.2
        elif sl_model == "SL_ATR_0_3":
            return 0.3
        elif sl_model == "SL_ATR_0_4":
            return 0.4
        elif sl_model == "SL_ATR_0_5":
            return 0.5
        elif sl_model == "SL_ATR_0_6":
            return 0.6
        elif sl_model == "SL_ATR_0_7":
            return 0.7
        elif sl_model == "SL_ATR_0_8":
            return 0.8
        elif sl_model == "SL_ATR_0_9":
            return 0.9
        elif sl_model == "SL_ATR_1_0":
            return 1.0
        elif sl_model == "SL_ATR_1_1":
            return 1.1
        elif sl_model == "SL_ATR_1_2":
            return 1.2
        elif sl_model == "SL_ATR_1_5":
            return 1.5
        # AOI-based SL distances
        elif sl_model == "SL_AOI_FAR":
            return self._geometry.aoi_far_edge_atr
        elif sl_model == "SL_AOI_FAR_PLUS_0_25":
            return self._geometry.aoi_far_edge_atr + 0.25
        elif sl_model == "SL_AOI_NEAR":
            return self._geometry.aoi_near_edge_atr
        elif sl_model == "SL_AOI_NEAR_PLUS_0_25":
            return self._geometry.aoi_near_edge_atr + 0.25
        # Signal candle-based SL distances
        elif sl_model == "SL_SIGNAL_CANDLE":
            return self._geometry.signal_candle_opposite_extreme_atr
        elif sl_model == "SL_SIGNAL_CANDLE_PLUS_0_1":
            return self._geometry.signal_candle_opposite_extreme_atr + 0.1
        elif sl_model == "SL_SIGNAL_CANDLE_PLUS_0_2":
            return self._geometry.signal_candle_opposite_extreme_atr + 0.2
        elif sl_model == "SL_SIGNAL_CANDLE_PLUS_0_25":
            return self._geometry.signal_candle_opposite_extreme_atr + 0.25
        elif sl_model == "SL_SIGNAL_CANDLE_PLUS_0_3":
            return self._geometry.signal_candle_opposite_extreme_atr + 0.3
        elif sl_model == "SL_SIGNAL_CANDLE_PLUS_0_4":
            return self._geometry.signal_candle_opposite_extreme_atr + 0.4
        elif sl_model == "SL_SIGNAL_CANDLE_PLUS_0_5":
            return self._geometry.signal_candle_opposite_extreme_atr + 0.5
        # Hybrid SL model
        elif sl_model == "SL_MAX_AOI_ATR_1_0":
            return max(self._geometry.aoi_far_edge_atr, 1.0)
        else:
            return None
    
    def _simulate_one(
        self,
        sl_model: str,
        rr_multiple: float,
        sl_atr: float,
        tp_atr: float,
    ) -> ExitSimulationRow:
        """Simulate exit for one SL × R configuration.
        
        Scans path to find first SL hit, TP hit, or timeout at bar 72.
        Uses high/low prices for hit detection (not close prices).
        """
        bars_to_sl_hit = None
        bars_to_tp_hit = None
        exit_reason = "TIMEOUT"
        exit_bar = OUTCOME_WINDOW_BARS
        mfe_atr = 0.0
        mae_atr = 0.0
        is_bad_pre48 = False
        
        for row in self._path:
            # Track overall MFE/MAE using high/low (intrabar extremes)
            if row.mfe_atr_high_low is not None:
                mfe_atr = max(mfe_atr, row.mfe_atr_high_low)
            if row.mae_atr_high_low is not None:
                mae_atr = min(mae_atr, row.mae_atr_high_low)
            
            # Check for SL hit using high/low (MAE reaches -sl_atr)
            if bars_to_sl_hit is None and row.mae_atr_high_low is not None:
                if row.mae_atr_high_low <= -sl_atr:
                    bars_to_sl_hit = row.bar_index
            
            # Check for TP hit using high/low (MFE reaches +tp_atr)
            if bars_to_tp_hit is None and row.mfe_atr_high_low is not None:
                if row.mfe_atr_high_low >= tp_atr:
                    bars_to_tp_hit = row.bar_index
            
            # Check for bad trade pre-48 (MAE hits SL before bar 48)
            if row.bar_index <= 48 and row.mae_atr_high_low is not None:
                if row.mae_atr_high_low <= -sl_atr:
                    is_bad_pre48 = True
        
        # Determine exit reason and bar
        if bars_to_sl_hit is not None and bars_to_tp_hit is not None:
            # Both hit - which came first?
            if bars_to_sl_hit <= bars_to_tp_hit:
                exit_reason = "SL"
                exit_bar = bars_to_sl_hit
            else:
                exit_reason = "TP"
                exit_bar = bars_to_tp_hit
        elif bars_to_sl_hit is not None:
            exit_reason = "SL"
            exit_bar = bars_to_sl_hit
        elif bars_to_tp_hit is not None:
            exit_reason = "TP"
            exit_bar = bars_to_tp_hit
        else:
            exit_reason = "TIMEOUT"
            exit_bar = len(self._path) if self._path else 0
        
        # Calculate return based on exit reason
        if exit_reason == "SL":
            return_atr = -sl_atr
        elif exit_reason == "TP":
            return_atr = tp_atr
        else:
            # Timeout - use return at last bar
            if self._path:
                return_atr = self._path[-1].return_atr_at_bar
            else:
                return_atr = 0.0
        
        return_r = return_atr / sl_atr if sl_atr > 0 else 0.0
        
        return ExitSimulationRow(
            sl_model=sl_model,
            rr_multiple=rr_multiple,
            sl_atr=sl_atr,
            tp_atr=tp_atr,
            exit_reason=exit_reason,
            exit_bar=exit_bar,
            return_atr=return_atr,
            return_r=return_r,
            mfe_atr=mfe_atr,
            mae_atr=mae_atr,
            bars_to_sl_hit=bars_to_sl_hit,
            bars_to_tp_hit=bars_to_tp_hit,
            is_bad_pre48=is_bad_pre48,
        )


def persist_exit_simulations(signal_id: int, rows: List[ExitSimulationRow]) -> None:
    """Persist exit simulation results to database."""
    from database.executor import DBExecutor
    from .replay_queries import INSERT_EXIT_SIMULATION
    
    if not rows:
        return
    
    def _persist(cursor):
        for row in rows:
            cursor.execute(
                INSERT_EXIT_SIMULATION,
                (
                    signal_id,
                    row.sl_model,
                    row.rr_multiple,
                    row.sl_atr,
                    row.tp_atr,
                    row.exit_reason,
                    row.exit_bar,
                    row.return_atr,
                    row.return_r,
                    row.mfe_atr,
                    row.mae_atr,
                    row.bars_to_sl_hit,
                    row.bars_to_tp_hit,
                    row.is_bad_pre48,
                ),
            )
    
    DBExecutor.execute_transaction(_persist, context="persist_exit_simulations")
