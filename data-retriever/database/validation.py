from typing import Optional, Union

import utils.display as display
from models import AOIZone


class DBValidator:
    @staticmethod
    def validate_symbol(symbol: str) -> Optional[str]:
        if not isinstance(symbol, str) or not symbol.strip():
            display.print_error("DB_VALIDATION: symbol must be a non-empty string")
            return None

        normalized = symbol.strip().upper()

        if len(normalized) > 20:
            display.print_error("DB_VALIDATION: symbol must be 20 characters or fewer")
            return None

        if not normalized.isalnum():
            display.print_error("DB_VALIDATION: symbol must be alphanumeric")
            return None

        return normalized

    @staticmethod
    def validate_timeframe(timeframe: str) -> Optional[str]:
        if not isinstance(timeframe, str) or not timeframe.strip():
            display.print_error("DB_VALIDATION: timeframe must be a non-empty string")
            return None

        normalized = timeframe.strip().upper()

        if len(normalized) > 20:
            display.print_error("DB_VALIDATION: timeframe must be 20 characters or fewer")
            return None

        if not normalized.isalnum():
            display.print_error("DB_VALIDATION: timeframe must be alphanumeric")
            return None

        return normalized

    @staticmethod
    def validate_nullable_float(value: Optional[float], field: str) -> bool:
        if value is None:
            return True
        if not isinstance(value, (int, float)):
            display.print_error(f"DB_VALIDATION: {field} must be a number or None")
            return False
        return True

    @staticmethod
    def validate_aoi(aoi: Union[dict, AOIZone]) -> bool:
        if isinstance(aoi, AOIZone):
            lower = aoi.lower
            upper = aoi.upper
        else:
            lower = aoi.get("lower_bound")
            upper = aoi.get("upper_bound")
        if not DBValidator.validate_nullable_float(lower, "lower_bound"):
            return False
        if not DBValidator.validate_nullable_float(upper, "upper_bound"):
            return False
        return True
