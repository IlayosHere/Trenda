"""Trading and signaling configuration."""
import os


# Trading & Signaling
MT5_ORDER_COMMENT: str = os.getenv("MT5_ORDER_COMMENT", "Trenda signal")
SIGNAL_SCORE_THRESHOLD: float = float(os.getenv("SIGNAL_SCORE_THRESHOLD", "4.0"))
