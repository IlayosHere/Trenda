from analyzers import analyze_by_timeframe, analyze_aoi_by_timeframe

SCHEDULE_CONFIG = {
    "job_hourly_aoi": {"timeframe": ["4H"], "interval_minutes": 240, "job": analyze_aoi_by_timeframe},
    "job_hourly_trend": {"timeframe": ["1H"], "interval_minutes": 60, "job": analyze_by_timeframe},
    "job_4_hour_trend": {"timeframe": ["4H"], "interval_minutes": 240, "job": analyze_by_timeframe},
    "job_daily_trend": {"timeframe": ["1D"], "interval_minutes": 1440, "job": analyze_by_timeframe},
}
