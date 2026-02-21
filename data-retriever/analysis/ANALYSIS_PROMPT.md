# Trenda — System Configuration Analysis

## Context

You are analyzing a Forex trend-following system called **Trenda (Snake-Line strategy)**.
The goal is to find the optimal combination of:
- **SL model** (stop-loss placement method)
- **RR multiple** (take-profit distance as a multiple of SL)
- **Gate set** (pre-entry filters that select only high-quality signals)

That satisfies:
- **Minimum 100 trades/year**
- **Maximum expectancy** (mean return in R units)
- **Minimum losing streaks**

---

## Input Files

| File | Description |
|------|-------------|
| `data-retriever/analysis/signals.csv` | One row per signal. Contains signal metadata + all pre-entry context features. |
| `data-retriever/analysis/exit_simulations.csv` | One row per (signal × sl_model × rr_multiple). Contains exit outcomes. |

Join key: `signals.id` = `exit_simulations.entry_signal_id`

---

## Fixed Filters (Already Applied in CSVs)

- `sl_model_version = 'CHECK_GEO'`
- `is_break_candle_last = TRUE`

No additional global filters. Analyze all data as-is.

---

## Exit Classification Rules

| `exit_reason` | Meaning |
|---------------|---------|
| `TP` | Win — price hit take-profit |
| `SL` | Loss — price hit stop-loss |
| `TIMEOUT` | Neither — 72 bars elapsed without SL or TP hit |

**Metrics to compute per configuration:**
- `win_pct` = TP / total
- `sl_pct` = SL / total
- `timeout_pct` = TIMEOUT / total
- `expectancy_r` = mean(`return_r`) across ALL trades (TP, SL, and TIMEOUT all have a `return_r` value)
- `max_losing_streak` = max consecutive SL exits. TIMEOUT does **not** count as a loss for streak purposes — only `SL` breaks/extends a losing streak
- `trades_per_year` = total trades / data span in years. Use the full dataset's date range as the denominator (not just the filtered subset's range), to avoid inflating the number when gates narrow the time window
- `profit_factor` = sum(positive `return_r`) / abs(sum(negative `return_r`))

---

## SL Model Catalog

| sl_model | SL distance in ATR |
|----------|-------------------|
| SL_ATR_0_5 | 0.5 |
| SL_ATR_1_0 | 1.0 |
| SL_ATR_1_5 | 1.5 |
| SL_ATR_2_0 | 2.0 |
| SL_AOI_FAR | Distance from entry to far AOI edge (opposite side of trade direction) |
| SL_AOI_FAR_PLUS_0_25 | Far AOI edge + 0.25 ATR buffer |
| SL_AOI_NEAR | Distance from entry to near AOI edge (same side as trade direction) |
| SL_AOI_NEAR_PLUS_0_25 | Near AOI edge + 0.25 ATR buffer |
| SL_AOI_NEAR_PLUS_0_5 | Near AOI edge + 0.5 ATR buffer |
| SL_SIGNAL_CANDLE | Distance from entry to opposite extreme of signal candle |
| SL_SIGNAL_CANDLE_PLUS_0_25 | Signal candle opposite extreme + 0.25 ATR buffer |

RR multiples available: 2.0, 2.5, 3.0, 3.5, 4.0

---

## Signal Features — Column Semantics

### From `entry_signal`

| Column | Type | Notes |
|--------|------|-------|
| `direction` | categorical | `'bullish'` or `'bearish'` |
| `trend_alignment_strength` | integer 1–3 | How many of the 3 trend TFs (4H/1D/1W) agree. Higher = stronger |
| `conflicted_tf` | varchar / NULL | Which timeframe conflicted at entry. NULL = no conflict (favorable). Non-null = a specific TF (e.g. `'4H'`) is conflicting |
| `hour_of_day_utc` | integer 0–23 | UTC hour of signal. Session buckets: Asia 0–5, London 6–11, NY 12–17, post-NY 18–23 |
| `aoi_touch_count_since_creation` | integer | How many times the AOI has been touched since it was created. Lower = fresher zone |
| `max_retest_penetration_atr` | float | Max depth the retest candle (before the break) penetrated into the AOI, in ATR |
| `bars_between_retest_and_break` | integer | 1H bars between the retest and the break/signal candle |

### From `pre_entry_context_v2`

**Direction-aware columns** (already normalized so positive = favorable regardless of trade direction. A single threshold works for both bullish and bearish):

| Column | Interpretation |
|--------|---------------|
| `session_directional_bias` | Session move in trade direction / ATR. Positive = session moving with the trade |
| `recent_trend_payoff_atr_24h` | Price move in trade direction over last 24h / ATR. Positive = momentum aligned |
| `recent_trend_payoff_atr_48h` | Same, over 48h |
| `break_close_location` | Where the break candle closed within its range. Bullish: (close−low)/(high−low). Bearish: (high−close)/(high−low). 1.0 = closed at the extreme in trade direction = max conviction |
| `distance_to_next_htf_obstacle_atr` | Distance to the nearest HTF level in trade direction (room to run). Higher = more room |
| `aoi_last_reaction_strength` | MFE in ATR of the previous reaction off this AOI. Higher = zone proved strong before |
| `distance_from_last_impulse_atr` | Distance from last large impulse bar to entry price. Lower = entry is close behind momentum |

**NOT direction-aware — need direction-split analysis:**

| Column | Interpretation |
|--------|---------------|
| `htf_range_position_mid` | Entry price position within the current daily candle range. 0=bottom, 1=top. **LONG wants low values (< 0.5), SHORT wants high values (> 0.5)** |
| `htf_range_position_high` | Same but weekly range |
| `aoi_midpoint_range_position_mid` | AOI midpoint position within daily range. Same direction logic as above |
| `aoi_midpoint_range_position_high` | Same but weekly range |

**Directionally ambiguous (analyze vs outcome to determine threshold direction):**

| Column | Interpretation |
|--------|---------------|
| `trend_age_bars_1h` | 1H bars since full 3-TF trend alignment began |
| `trend_age_impulses` | Count of directional impulse runs in the last 50 bars |
| `aoi_height_atr` | Vertical size of AOI in ATR. Smaller = tighter, more precise zone |
| `break_impulse_range_atr` | Break candle total range / ATR |
| `break_impulse_body_atr` | Break candle body / ATR |
| `htf_range_size_mid_atr` | Total daily range size over last 20 daily candles / ATR. Indicates market expansion |
| `htf_range_size_high_atr` | Total weekly range size over last 12 weekly candles / ATR |
| `aoi_time_since_last_touch` | 1H bars since the AOI was last touched before this signal |

### From `sl_geometry_unbiased`

| Column | Interpretation |
|--------|---------------|
| `signal_candle_opposite_extreme_atr` | Distance from entry to the low (bullish) or high (bearish) of the signal candle / ATR |
| `signal_candle_range_atr` | Total signal candle range / ATR |
| `signal_candle_body_atr` | Signal candle body / ATR |
| `aoi_far_edge_atr` | Distance from entry to far AOI edge / ATR |
| `aoi_near_edge_atr` | Distance from entry to near AOI edge / ATR |
| `geo_aoi_height_atr` | AOI height / ATR (from geometry calculation, cross-check with pec version) |

---

## Analysis Phases

### Phase 1 — EDA
- Total signal count, date range, signals per year
- Direction split (bullish vs bearish counts)
- Null coverage per feature column (flag any column >20% null)
- Exit reason distribution overall and per (sl_model, rr_multiple)
- `return_r` distribution per sl_model (box plots or percentiles)

### Phase 2 — Baseline Sweep
For every (sl_model × rr_multiple) combination with **no gates**:
- Compute all metrics
- Run three slices: ALL signals, BULLISH only, BEARISH only
- Enforce minimum 100 trades/year
- Rank by `expectancy_r` descending
- Show: sl_model, rr_multiple, direction_filter, n_trades, trades_per_year, win_pct, sl_pct, timeout_pct, expectancy_r, max_losing_streak, profit_factor

Identify **top 5 configurations** to carry into Phase 3.

### Phase 3 — Single-Gate Sweep
For each of the top-5 baseline configs, test every gate candidate:

**Categorical gates:** `direction` (already split above); `conflicted_tf IS NULL` vs non-null (boolean gate); also test each unique non-null value of `conflicted_tf` to see if a specific conflicting TF is more/less harmful than others

**Ordinal gates:** `trend_alignment_strength >= 2`, `>= 3`; `aoi_touch_count_since_creation <= 1`, `<= 2`, `<= 3`

**Numerical gates (sweep p25/p50/p75 as thresholds):**
- Direction-aware columns: test `column >= threshold`
- `aoi_height_atr`: test `column <= threshold` (smaller is better)
- `distance_from_last_impulse_atr`: test both directions to determine which is better
- `htf_range_position_mid/high` and `aoi_midpoint_*`: test SEPARATELY per direction:
  - BULLISH: `column <= threshold`
  - BEARISH: `column >= threshold`

**Hour-of-day gates:** test `hour_of_day_utc` in ranges: [6–11] (London), [12–17] (NY), [6–17] (London+NY combined), specific single hours

For each gate result, show: delta_expectancy vs baseline, trades retained (%), max_losing_streak change.

### Phase 4 — Multi-Gate Greedy Combination
For the top baseline config (and top direction-split config if different):
1. Start with best single gate
2. Add the next gate that most improves `expectancy_r` while keeping trades_per_year ≥ 100
3. Repeat until adding any further gate fails to improve expectancy or drops below 100 trades/year
4. Also brute-force test all combinations of depth-2 and depth-3 from the top-10 single gates

Report: final gate set, all metrics, and the improvement at each greedy step.

### Phase 5 — Output
Write a ranked CSV: `data-retriever/analysis/results.csv`

Columns: `gate_type` (baseline/single/multi), `direction_filter`, `sl_model`, `rr_multiple`, `gates`, `n_trades`, `trades_per_year`, `win_pct`, `sl_pct`, `timeout_pct`, `expectancy_r`, `max_losing_streak`, `profit_factor`

Print the top-20 rows to the console at the end.

---

## Key Analytical Questions to Answer

1. **Is there a meaningful difference in performance between bullish and bearish signals?** If yes, should they be traded with different gate sets?
2. **Which features have the strongest correlation with `return_r`?** (Compute Spearman correlation for numerical features, mean return by category for categoricals.)
3. **Which SL model family performs best?** (Fixed ATR vs AOI-based vs signal candle-based)
4. **What is the timeout rate across configurations?** High timeout rates may indicate the RR is set too far.
5. **Do any gates dramatically reduce losing streaks without significantly cutting trade volume?**
