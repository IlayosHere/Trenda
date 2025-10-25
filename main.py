import time
from scheduler import scheduler
from logic import mt5_connector
from scheduler import start_scheduler
import display


def main():
    display.print_status("--- 🚀 Starting Trend Analyzer Bot ---")

    if not mt5_connector.initialize_mt5():
        return  # Exit if MT5 can't start

    try:
        start_scheduler()

        # 3. Keep the main script alive to let the scheduler run
        while True:
            # Sleep for a long time; the scheduler runs on its own thread.
            time.sleep(3600)

    except Exception as e:
        display.print_error(f"An unexpected error occurred in main: {e}")

    finally:
        # 4. Always shut down MT5 and scheduler
        if scheduler.running:
            scheduler.shutdown()
        mt5_connector.shutdown_mt5()


# --- Run the bot ---
if __name__ == "__main__":
    main()
