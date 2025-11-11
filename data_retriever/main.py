from __future__ import annotations

import time

from data_retriever.scheduler import scheduler, start_scheduler
from data_retriever.externals import mt5_handler
from data_retriever.utils import display


def main() -> None:
    display.print_status("--- 🚀 Starting Trend Analyzer Bot ---")

    if not mt5_handler.initialize_mt5():
        return  # Exit if MT5 can't start

    try:
        start_scheduler()

        # 3. Keep the main script alive to let the scheduler run
        while True:
            # Sleep for a long time; the scheduler runs on its own thread.
            time.sleep(3600)

    except KeyboardInterrupt:
        display.print_status("Received shutdown signal. Cleaning up...")
    except Exception as exc:  # pragma: no cover - defensive logging
        display.print_error(f"An unexpected error occurred in main: {exc}")

    finally:
        # 4. Always shut down MT5 and scheduler
        if scheduler.running:
            scheduler.shutdown()
        mt5_handler.shutdown_mt5()


# --- Run the bot ---
if __name__ == "__main__":
    main()
