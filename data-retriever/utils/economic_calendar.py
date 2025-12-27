import pandas as pd
import os
from datetime import datetime, timedelta

# Cache for the dataset to avoid repeated reads within the same process session
_forex_calendar_df = None

def check_high_impact_events(pair, target_date_str):
    """
    Checks for all economic events within ±2 days of the given date for a single forex pair.
    Uses the local forex_factory_cache.csv file.
    
    Args:
        pair (str): Forex pair (e.g., "EURUSD")
        target_date_str (str): Date in YYYY-MM-DD format
        
    Returns:
        dict: {
            "exists": bool,
            "events": list of {
                "name": str,
                "date": str,
                "currency": str
            }
        }
    """
    global _forex_calendar_df
    
    try:
        # 1. Load dataset (cached in-memory)
        if _forex_calendar_df is None:
            # Get the path to the local CSV file (in the same directory as this script)
            base_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(base_dir, "forex_factory_cache.csv")
            
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Economic calendar CSV not found at: {file_path}")
            
            # The CSV has no header: DateTime, Currency, Event, Description (ignored)
            # Example: 2022-01-04T18:30:00+03:30,USD,ISM Manufacturing PMI,"..."
            column_names = ['DateTime', 'Currency', 'Event', 'Description']
            _forex_calendar_df = pd.read_csv(file_path, names=column_names, on_bad_lines='skip')
            
            # Extract just the YYYY-MM-DD part and parse it as a date
            # This ensures we match exactly what is written in the CSV file regardless of offsets
            _forex_calendar_df['DateTime'] = pd.to_datetime(_forex_calendar_df['DateTime'].str[:10])

        # 2. Setup date range (±2 days)
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
        # Ensure target_date is UTC-aware for comparison if DateTime is
        target_date_utc = target_date.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(None)
        
        date_from = target_date - timedelta(days=2)
        date_to = target_date + timedelta(days=2)
        
        # 3. Filter for relevant currencies
        # Extract individual currencies (e.g., EUR and USD from EURUSD)
        currencies = [pair[:3].upper(), pair[3:].upper()]
        
        # Filter by Date range (±2 days) and Currencies
        # Use .dt.date for comparison against date objects
        mask = (
            (_forex_calendar_df['DateTime'].dt.date >= date_from.date()) &
            (_forex_calendar_df['DateTime'].dt.date <= date_to.date()) &
            (_forex_calendar_df['Currency'].isin(currencies))
        )
        
        filtered_events = _forex_calendar_df.loc[mask]
        
        # 4. Format results
        events = []
        for _, row in filtered_events.iterrows():
            # Use the original string part of the DateTime to avoid timezone shifts when displaying
            # row['DateTime'] is a Timestamp object, we want the date as it appears in the source
            events.append({
                "name": row['Event'],
                "date": str(row['DateTime'].date()), # This returns YYYY-MM-DD based on the parsed values
                "currency": row['Currency']
            })
            
        return {
            "exists": len(events) > 0,
            "events": events
        }
        
    except Exception as e:
        print(f"Error checking economic calendar: {e}")
        return {"exists": False, "events": [], "error": str(e)}

# Example usage with a single pair and a single date
# if __name__ == "__main__":
#     test_pair = "USDAUD"
#     test_date = "2022-01-30"
    
#     print(f"Checking {test_pair} for events around {test_date} (±2 days)...")
#     res = check_high_impact_events(test_pair, test_date)
    
#     if res["exists"]:
#         print(f"Found {len(res['events'])} event(s):")
#         for ev in res["events"]:
#             print(f"- {ev['currency']}: {ev['name']} ({ev['date']})")
#     else:
#         print("No events found.")
