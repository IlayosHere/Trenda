import time

import utils.display as display
from scheduler import scheduler, start_scheduler


def main():
    display.print_status("--- 🚀 Starting Trend Analyzer Bot ---")

    try:
        start_scheduler()

        # 3. Keep the main script alive to let the scheduler run
        while True:
            # Sleep for a long time; the scheduler runs on its own thread.
            time.sleep(3600)

    except Exception as e:
        display.print_error(f"An unexpected error occurred in main: {e}")

    finally:
        # 4. Always shut down the scheduler
        if scheduler.running:
            scheduler.shutdown()


# --- Run the bot ---
if __name__ == "__main__":
    main()
