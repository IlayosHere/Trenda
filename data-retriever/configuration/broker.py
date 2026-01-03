"""Broker selection and provider-specific configuration."""
from __future__ import annotations

import os
from typing import Final, Literal

BrokerProvider = Literal["MT5", "TWELVEDATA"]

BROKER_MT5: Final[BrokerProvider] = "MT5"
BROKER_TWELVEDATA: Final[BrokerProvider] = "TWELVEDATA"

BROKER_PROVIDER: BrokerProvider = os.getenv("BROKER_PROVIDER")

TWELVEDATA_API_KEY: str | None = os.getenv("TWELVEDATA_API_KEY")
TWELVEDATA_BASE_URL: str = os.getenv("TWELVEDATA_BASE_URL", "https://api.twelvedata.com")

# MT5 Config
MT5_MAGIC_NUMBER: int = int(os.getenv("MT5_MAGIC_NUMBER", "123456"))
MT5_DEVIATION: int = int(os.getenv("MT5_DEVIATION", "20"))
MT5_DEFAULT_LOT_SIZE: float = float(os.getenv("MT5_DEFAULT_LOT_SIZE", "0.01"))
MT5_EXPIRATION_MINUTES: int = int(os.getenv("MT5_EXPIRATION_MINUTES", "10"))

# Trading Strategy Config
TRADE_QUALITY_THRESHOLD: float = float(os.getenv("TRADE_QUALITY_THRESHOLD", "0.5"))
