import requests
import json
import os
from datetime import datetime, timedelta

# In-memory cache to avoid repeated file reads within the same script execution
_cached_events_data = None
_last_app_fetch_time = None

def check_high_impact_events(pair, target_date_str):
    """
    Checks for high-impact economic events within +-2 days of the given date for a forex pair.
    Uses a cached version of the Forex Factory weekly calendar to avoid rate limits.
    """
    global _cached_events_data, _last_app_fetch_time
    
    try:
        # Cache configuration
        # Using full path to avoid issues with current working directory
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cache_file = os.path.join(base_dir, "ff_calendar_cache.json")
        cache_expiry_hours = 6
        
        # 1. Ensure the cache file exists and is up to date
        now = datetime.now()
        should_fetch = True
        
        # Check if we need to fetch new data
        if os.path.exists(cache_file):
            file_mod_time = datetime.fromtimestamp(os.path.getmtime(cache_file))
            if (now - file_mod_time) < timedelta(hours=cache_expiry_hours):
                should_fetch = False
        
        if should_fetch:
            # 2. Fetch Weekly Calendar JSON (Free Public Feed)
            # This part ONLY fills/updates the cache file
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            raw_data = response.json()
            
            # Filter for High impact events for ALL currencies
            high_impact_data = [e for e in raw_data if e.get("impact") == "High"]
            
            # Save to cache file
            with open(cache_file, "w") as f:
                json.dump(high_impact_data, f)
            
            # Reset in-memory cache to force a reload from the new file
            _cached_events_data = None

        # 3. Perform the search ONLY using the data from the cache file
        # (Using _cached_events_data to avoid redundant disk reads if already loaded)
        if _cached_events_data is None:
            if not os.path.exists(cache_file):
                return {"exists": False, "events": [], "error": "Calendar cache file missing and fetch failed."}
            
            with open(cache_file, "r") as f:
                _cached_events_data = json.load(f)
        
        events_data = _cached_events_data

        if events_data is None:
            return {"exists": False, "events": [], "error": "Failed to load calendar data from cache."}

        # 3. Parse currencies from pair
        currencies = [pair[:3].upper(), pair[3:].upper()]
        
        # 4. Parse target date and range
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
        start_range = target_date - timedelta(days=2)
        end_range = target_date + timedelta(days=2)
        
        matches = []
        
        for event in events_data:
            # Currency filtering: Either currency in the pair
            # (Note: Impact is already pre-filtered to "High" for ALL currencies in the cache)
            event_currency = (event.get("currency") or event.get("country") or "").upper()
            if event_currency not in currencies:
                continue
            
            # Date filtering: +- 2 days
            try:
                event_date_str = event.get("date", "").split("T")[0]
                event_date = datetime.strptime(event_date_str, "%Y-%m-%d")
                
                if start_range <= event_date <= end_range:
                    matches.append({
                        "name": event.get("title"),
                        "date": event_date_str,
                        "currency": event_currency,
                        "impact": event.get("impact")
                    })
            except (ValueError, IndexError):
                continue
                
        return {
            "exists": len(matches) > 0,
            "events": matches
        }
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
             return {"exists": False, "events": [], "error": "Rate limit hit (429). Please wait and try again."}
        return {"exists": False, "events": [], "error": str(e)}
    except Exception as e:
        print(f"Error checking economic calendar: {e}")
        return {"exists": False, "events": [], "error": str(e)}

# Example usage with a single pair and a single date
# if __name__ == "__main__":
#     test_pair = "USDCAD"
#     # Use today's date for current week feed
#     test_date = datetime.now().strftime("%Y-%m-%d")
    
#     print(f"Checking high-impact events for {test_pair} around {test_date}...")
#     result = check_high_impact_events(test_pair, test_date)
    
#     if result["exists"]:
#         print(f"Found {len(result['events'])} high-impact event(s):")
#         for ev in result["events"]:
#             print(f"- {ev['name']} ({ev['date']}) for {ev['currency']}")
#     else:
#         if "error" in result:
#             print(f"Error: {result['error']}")
#         else:
#             print("No high-impact events found.")