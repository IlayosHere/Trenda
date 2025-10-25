import oandapyV20
import oandapyV20.endpoints.instruments as instruments
from oandapyV20.exceptions import V20Error
from typing import Optional, Dict, Any

# Import config and display utility
from configuration import OANDA_ACCESS_TOKEN, OANDA_ENVIRONMENT
import utils.display as display


class OandaHandler:
    def __init__(self):
        self.client: Optional[oandapyV20.API] = None
        self._initialize_client()

    def _initialize_client(self):
        """Sets up the API client instance."""
        if not OANDA_ACCESS_TOKEN:
            display.print_error("OANDA Handler: OANDA_ACCESS_TOKEN is not configured.")
            return

        try:
            self.client = oandapyV20.API(
                access_token=OANDA_ACCESS_TOKEN, environment=OANDA_ENVIRONMENT
            )
            # Optional: Perform a quick test request to verify connection/token
            # self.test_connection() # Example method call
            display.print_status("✅ OANDA API client initialized successfully.")
        except Exception as e:
            display.print_error(
                f"OANDA Handler: Unexpected error initializing API: {e}"
            )
            self.client = None

    def is_connected(self) -> bool:
        """Checks if the client was initialized successfully."""
        return self.client is not None

    def get_candles(self, instrument: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_connected():
            # Raise a specific error or handle as appropriate
            raise ConnectionError("OANDA API client is not initialized.")

        try:
            request = instruments.InstrumentsCandles(
                instrument=instrument, params=params
            )
            response = self.client.request(request)
            return response
        except V20Error as e:
            # Re-raise V20Error so the caller (data_fetcher) can handle retries
            raise e
        except Exception as e:
            # Wrap other exceptions if needed, or re-raise
            display.print_error(
                f"OANDA Handler: Unexpected error during get_candles for {instrument}: {e}"
            )
            raise e  # Re-raise the original exception


# --- Create a single instance to be used by other modules ---
# This makes it easy to import and use the configured client.
oanda_handler = OandaHandler()
