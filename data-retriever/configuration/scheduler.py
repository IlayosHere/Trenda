from analyzers import analyze_by_timeframe, analyze_aoi_by_timeframe

SCHEDULE_CONFIG = {
    "job_4_hour_aoi": {"timeframe": ["4H"], "interval_minutes": 240, "job": analyze_aoi_by_timeframe},
    # "job_daily_aoi": {"timeframe": ["1D"], "interval_minutes": 1440, "job": analyze_aoi_by_timeframe},
    "job_4_hour_trend": {"timeframe": ["4H"], "interval_minutes": 240, "job": analyze_by_timeframe},
    "job_daily_trend": {"timeframe": ["1D"], "interval_minutes": 1440, "job": analyze_by_timeframe},
    "job_weekly_trend": {"timeframe": ["1W"], "interval_minutes": 10080, "job": analyze_by_timeframe},
}
