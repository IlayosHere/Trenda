# Agent Task Brief — Correlation Stability Analysis

## System Context

- **Project**: Trenda — Forex Trend Analysis System (Snake-Line strategy)
- **DB**: PostgreSQL, schema `trenda_replay`
- **Core script**: `data-retriever/analysis/portfolio_finder_v5.py`
- **RR multiple**: 2:1 (fixed). Breakeven = 33.33%.

---

## What Has Been Established

### Signal volume
- ~26,550 total signals across 7 years (2019–2025), ~3,800/year
- System targets 200–300 trades/year → ~7% selection ratio
- The baseline is expected to be weak — the gates ARE the filter, not a correction to a strong signal

### Raw baseline (no gates, all years combined)
From `raw_signal_baseline.csv`:
- **No cell × SL combination exceeds 35% raw win%**
- Best: `comm|bear` at 34.8%, `jpy|bear` at 33.8%, `jpy|bull` at 33.5%
- Bull cells mostly below breakeven (33.33%)
- `SL_AOI_NEAR` is outlier-bad (23–25% win) — exclude from all analysis

### Gate search failure (nested LOO)
`portfolio_finder_v5.py` Stage 2 sweeps pre-defined gate thresholds and selects by `expectancy × TPY`.
After fixing Stage 3 to proper nested LOO (gate selected on 6-year train, tested on held-out year):
- **0 portfolios survive** Stage 4 hard constraints (exp > 0 + win >= 40% every year)
- Root cause: gates are threshold-optimised in-sample — they do not generalise
- The gate selection method finds correlations that are outcome-fitted, not structural

### Why gates fail
The current approach selects the gate that maximises `exp × TPY` on training data.
This is a greedy threshold search — it will always find a threshold that looks good in-sample,
but the specific cutoff (e.g. `sb >= 0.5`) has no guarantee of being the true structural boundary.

---

## The Next Task

**Build a correlation stability analysis** across all pre-entry parameters.

### Hypothesis
Some pre-entry context variables genuinely predict win/loss outcome better than random.
These variables will show a **consistent directional correlation** across all 7 years independently —
even if the magnitude varies. Variables that flip direction year to year are noise.

### What to build: `correlation_stability.py`

For each numeric pre-entry parameter x each cell (group x direction):

1. **Split at median** (not a fixed threshold): for each year separately, split signals into
   top-half and bottom-half by that parameter value. Compute win% for each half.
2. **Directionality check**: does the higher-value half consistently have higher win% than
   the lower-value half across years? Record: `consistent_up`, `consistent_down`, `mixed`.
3. **Magnitude**: average win% lift (top half minus bottom half) across years where direction is consistent.
4. **Stability score**: number of years where direction holds (0–7). A parameter with 7/7
   consistent direction is structurally predictive. A 4/7 is noise.

### Parameters to analyse
All numeric columns available in the dataset (from the SQL in `portfolio_finder_v5.py`):
- `htf_range_position_mid`, `htf_range_position_high`
- `session_directional_bias`
- `break_close_location`, `break_impulse_range_atr`, `break_impulse_body_atr`
- `retest_candle_body_penetration`
- `aoi_height_atr`, `distance_to_next_htf_obstacle_atr`, `distance_from_last_impulse_atr`
- `recent_trend_payoff_atr_24h`, `recent_trend_payoff_atr_48h`
- `aoi_time_since_last_touch`, `aoi_last_reaction_strength`
- `htf_range_size_mid_atr`, `aoi_midpoint_range_position_mid`
- `trend_age_bars_1h`, `trend_age_impulses`
- `max_retest_penetration_atr`, `bars_between_retest_and_break`
- `aoi_touch_count_since_creation`
- `signal_candle_range_atr`, `signal_candle_body_atr`
- `aoi_near_edge_atr`, `aoi_far_edge_atr`
- `opp_extreme` (signal_candle_opposite_extreme_atr)
- `trend_alignment_strength` (ordinal: 1, 2, 3)
- `hour_of_day_utc` (ordinal)
- `conflicted_tf` (binary: NULL = no conflict)

### Output
- Console: ranked list of parameters per cell by stability score (7/7 down to 0/7), showing avg win% lift
- CSV: `correlation_stability.csv` — one row per (cell, parameter), columns:
  `cell, param, direction, stability_score, avg_lift_pp, years_detail`

### Key constraints
- Use the same DB connection pattern as `portfolio_finder_v5.py` (`POSTGRES_DB`, psycopg2)
- Use the same SQL query already in `portfolio_finder_v5.py` — load full dataset once
- No `print()` for logging — use project logger. `print()` only for formatted table output
- Strict PEP 8, type hints, snake_case
- Standalone script — does not modify `portfolio_finder_v5.py`
- Per-year sample sizes are small (~400–600/year per cell across all SL models combined) —
  use median split (not fixed thresholds) to maximise n per half

### Interpretation guide
- **Stability 7/7 + lift >= 3pp**: strong structural signal, primary gate candidate
- **Stability 6/7 + lift >= 2pp**: credible, worth testing
- **Stability <= 5/7**: noise — discard regardless of lift magnitude
- Parameters stable for bearish cells but not bullish (or vice versa) are directionally
  specific — that is valid and expected

---

## File Locations
```
data-retriever/
  analysis/
    portfolio_finder_v5.py     <- main pipeline (do not modify)
    raw_signal_baseline.csv    <- raw win% per cell x SL (reference)
    correlation_stability.py   <- NEW FILE to build
    correlation_stability.csv  <- output
  configuration/
    db_config.py               <- POSTGRES_DB dict
  logger.py                    <- get_logger(name)
```

## Run Command
```bash
cd data-retriever && python analysis/correlation_stability.py
```
