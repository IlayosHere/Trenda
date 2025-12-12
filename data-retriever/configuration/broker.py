"""Broker selection and provider-specific configuration."""
from __future__ import annotations

import os
from typing import Final, Literal

BrokerProvider = Literal["MT5", "TWELVEDATA"]

BROKER_MT5: Final[BrokerProvider] = "MT5"
BROKER_TWELVEDATA: Final[BrokerProvider] = "TWELVEDATA"

BROKER_PROVIDER: BrokerProvider = os.getenv("BROKER_PROVIDER", BROKER_MT5).upper()  # type: ignore[assignment]

TWELVEDATA_API_KEY: str | None = os.getenv("TWELVEDATA_API_KEY")
TWELVEDATA_BASE_URL: str = os.getenv("TWELVEDATA_BASE_URL", "https://api.twelvedata.com")
