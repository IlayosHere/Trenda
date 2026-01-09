"""Broker selection and provider-specific configuration."""
from __future__ import annotations

import os
from typing import Final, Literal

BrokerProvider = Literal["MT5", "TWELVEDATA"]

BROKER_MT5: Final[BrokerProvider] = "MT5"
BROKER_TWELVEDATA: Final[BrokerProvider] = "TWELVEDATA"

BROKER_PROVIDER: BrokerProvider = os.getenv("BROKER_PROVIDER", "MT5")

# MT5 broker timezone offset from UTC (in hours)
# Most MT5 brokers run on EET/EEST (Eastern European Time) which is UTC+2 (or UTC+3 in summer)
# Set this to the GMT offset of your broker's server
# This is used to convert broker timestamps to true UTC
MT5_BROKER_UTC_OFFSET: int = int(os.getenv("MT5_BROKER_UTC_OFFSET", "2"))

TWELVEDATA_API_KEY: str | None = os.getenv("TWELVEDATA_API_KEY")
TWELVEDATA_BASE_URL: str = os.getenv("TWELVEDATA_BASE_URL", "https://api.twelvedata.com")

