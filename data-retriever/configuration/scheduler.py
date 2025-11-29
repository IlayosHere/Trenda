from analyzers import analyze_trend_by_timeframe, analyze_aoi_by_timeframe, run_1h_entry_scan_job
from utils.bot_check import run_bot_check

SCHEDULE_CONFIG = {
    "job_1_hour_cnadles": {"timeframe": ["1H"], "interval_minutes": 60, "job": run_1h_entry_scan_job},
    # "job_4_hour_trend": {"timeframe": ["4H"], "interval_minutes": 240, "job": analyze_trend_by_timeframe},
    # "job_daily_trend": {"timeframe": ["1D"], "interval_minutes": 1440, "job": analyze_trend_by_timeframe},
    # "job_weekly_trend": {"timeframe": ["1W"], "interval_minutes": 10080, "job": analyze_trend_by_timeframe},
    # "job_4_hour_aoi": {"timeframe": ["4H"], "interval_minutes": 240, "job": analyze_aoi_by_timeframe},
    # "job_daily_aoi": {"timeframe": ["1D"], "interval_minutes": 1440, "job": analyze_aoi_by_timeframe},
# 
}
