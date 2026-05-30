"""
Compute Customer Baseline Load (CBL) and DR event performance using HighXofY.

Industry method (simplified):
  1. Select 10 non-event lookback days before the event
  2. Keep the top 5 days by total usage during event hours
  3. Average interval-level usage across those 5 days = raw CBL
  4. Apply morning adjustment (±20% cap) based on 2-hour pre-event actual vs CBL

Note: interval_clean contains event-day windows only (not full AMI history). When
historical lookback days are absent, this script synthesizes 10 pre-event days from
each customer's event-day profile using a deterministic seed so HighXofY logic can
still run end-to-end in the demo pipeline.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_PATH = PROCESSED_DIR / "cbl_performance.parquet"

LOOKBACK_DAYS = 10
TOP_DAYS = 5
INTERVAL_HOURS = 0.25
PRE_EVENT_HOURS = 2
RESPONSE_THRESHOLD_KW = 0.1
MORNING_ADJ_CAP = 0.20
VARIANCE_THRESHOLD = 0.30


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    intervals = pd.read_parquet(PROCESSED_DIR / "interval_clean.parquet")
    dr_events = pd.read_parquet(PROCESSED_DIR / "db_dr_events_clean.parquet")
    intervals["interval_ts"] = pd.to_datetime(intervals["interval_start_local"], errors="coerce")
    intervals["interval_time"] = intervals["interval_ts"].dt.strftime("%H:%M")
    intervals["event_date"] = intervals["interval_ts"].dt.normalize()
    return intervals, dr_events


def event_window_bounds(group: pd.DataFrame) -> dict:
    event_rows = group[group["is_event_window"] == 1].sort_values("interval_ts")
    pre_rows = group[group["is_event_window"] == 0].sort_values("interval_ts")
    if event_rows.empty:
        return {}

    event_start = event_rows["interval_ts"].min()
    event_end = event_rows["interval_ts"].max() + pd.Timedelta(minutes=15)
    morning_start = event_start - pd.Timedelta(hours=PRE_EVENT_HOURS)

    return {
        "event_start": event_start,
        "event_end": event_end,
        "morning_start": morning_start,
        "event_times": event_rows["interval_time"].tolist(),
        "morning_times": pre_rows.loc[
            pre_rows["interval_ts"] >= morning_start, "interval_time"
        ].tolist(),
    }


def synthesize_lookback_days(
    account_id: str,
    event_id: int,
    event_date: pd.Timestamp,
    event_times: list[str],
    morning_times: list[str],
    event_day_profile: pd.DataFrame,
) -> tuple[pd.DataFrame, int, bool]:
    """
    Build 10 synthetic non-event lookback days when AMI history is unavailable.
    Returns daily interval usage, count of clean days, and whether any E-flags appear.
    """
    rng = np.random.default_rng(abs(hash((account_id, int(event_id)))) % (2**32))

    pre_event_mean = float(
        event_day_profile.loc[event_day_profile["is_event_window"] == 0, "usage_kwh"].mean()
    )
    if np.isnan(pre_event_mean):
        pre_event_mean = 0.8

    # Counterfactual event-hour load is modeled above the pre-event shoulder.
    base_event = pre_event_mean * 1.18
    base_morning = pre_event_mean

    records: list[dict] = []
    estimated_used = False
    clean_days = 0

    for offset in range(1, LOOKBACK_DAYS + 1):
        day = event_date - pd.Timedelta(days=offset)
        day_multiplier = float(rng.uniform(0.85, 1.15))
        use_estimated = bool(rng.random() < 0.06)
        if use_estimated:
            estimated_used = True

        day_total = 0.0
        for slot in event_times:
            slot_noise = float(rng.uniform(0.9, 1.1))
            value = max(0.05, base_event * day_multiplier * slot_noise)
            records.append(
                {
                    "lookback_date": day,
                    "interval_time": slot,
                    "usage_kwh": round(value, 3),
                    "data_quality_flag": "E" if use_estimated else "A",
                    "window": "event",
                }
            )
            day_total += value

        for slot in morning_times:
            slot_noise = float(rng.uniform(0.9, 1.1))
            value = max(0.05, base_morning * day_multiplier * slot_noise)
            records.append(
                {
                    "lookback_date": day,
                    "interval_time": slot,
                    "usage_kwh": round(value, 3),
                    "data_quality_flag": "E" if use_estimated else "A",
                    "window": "morning",
                }
            )

        records.append(
            {
                "lookback_date": day,
                "interval_time": "_daily_total",
                "usage_kwh": day_total,
                "data_quality_flag": "E" if use_estimated else "A",
                "window": "event_total",
            }
        )
        clean_days += 1

    return pd.DataFrame(records), clean_days, estimated_used


def select_top_baseline_days(lookback: pd.DataFrame) -> pd.DataFrame:
    totals = lookback[lookback["window"] == "event_total"].copy()
    top_days = (
        totals.sort_values("usage_kwh", ascending=False)
        .head(TOP_DAYS)["lookback_date"]
        .tolist()
    )
    return lookback[
        (lookback["lookback_date"].isin(top_days)) & (lookback["window"].isin(["event", "morning"]))
    ]


def compute_cbl_for_customer_event(
    account_id: str,
    event_id: int,
    meter_id: str,
    event_date: pd.Timestamp,
    actual_intervals: pd.DataFrame,
    bounds: dict,
) -> tuple[pd.DataFrame, dict]:
    event_times = bounds["event_times"]
    morning_times = bounds["morning_times"]
    morning_start = bounds["morning_start"]
    event_start = bounds["event_start"]

    lookback, clean_days, estimated_in_history = synthesize_lookback_days(
        account_id,
        event_id,
        event_date,
        event_times,
        morning_times,
        actual_intervals,
    )

    selected = select_top_baseline_days(lookback)
    selected_event = selected[selected["window"] == "event"]
    selected_morning = selected[selected["window"] == "morning"]

    cbl_event = (
        selected_event.groupby("interval_time")["usage_kwh"]
        .mean()
        .reindex(event_times)
    )
    cbl_morning = (
        selected_morning.groupby("interval_time")["usage_kwh"]
        .mean()
        .reindex(morning_times)
    )

    actual_event = (
        actual_intervals[actual_intervals["is_event_window"] == 1]
        .groupby("interval_time")["usage_kwh"]
        .mean()
        .reindex(event_times)
    )
    actual_morning = (
        actual_intervals[
            (actual_intervals["is_event_window"] == 0)
            & (actual_intervals["interval_ts"] >= morning_start)
            & (actual_intervals["interval_ts"] < event_start)
        ]
        .groupby("interval_time")["usage_kwh"]
        .mean()
        .reindex(morning_times)
    )

    actual_morning_total = actual_morning.sum(skipna=True)
    cbl_morning_total = cbl_morning.sum(skipna=True)
    if cbl_morning_total > 0 and pd.notna(actual_morning_total):
        raw_factor = actual_morning_total / cbl_morning_total
    else:
        raw_factor = 1.0
    adjustment_factor = float(np.clip(raw_factor, 1 - MORNING_ADJ_CAP, 1 + MORNING_ADJ_CAP))
    adjusted_cbl_event = cbl_event * adjustment_factor

    day_totals = lookback[lookback["window"] == "event_total"]["usage_kwh"]
    baseline_mean = day_totals.mean()
    baseline_std = day_totals.std()
    high_variance = bool(
        baseline_mean > 0 and pd.notna(baseline_std) and (baseline_std / baseline_mean) > VARIANCE_THRESHOLD
    )

    insufficient = clean_days < TOP_DAYS
    estimated_reads = estimated_in_history or bool(
        (selected["data_quality_flag"] == "E").any()
    )

    interval_rows: list[dict] = []
    for slot in event_times:
        cbl_val = float(adjusted_cbl_event.get(slot, np.nan))
        actual_val = float(actual_event.get(slot, np.nan))
        if pd.isna(actual_val):
            continue
        reduction_kwh = cbl_val - actual_val
        interval_rows.append(
            {
                "utility_account_id": account_id,
                "meter_id": meter_id,
                "event_id": event_id,
                "event_date": event_date,
                "interval_time": slot,
                "cbl_kwh": round(cbl_val, 4),
                "actual_kwh": round(actual_val, 4),
                "reduction_kwh": round(reduction_kwh, 4),
                "reduction_kw": round(reduction_kwh / INTERVAL_HOURS, 4),
            }
        )

    interval_df = pd.DataFrame(interval_rows)
    if interval_df.empty:
        return interval_df, {}

    avg_kw_reduced = interval_df["reduction_kw"].mean()
    max_kw_reduced = interval_df["reduction_kw"].max()
    responded_flag = bool(avg_kw_reduced > RESPONSE_THRESHOLD_KW)

    quality_score = 100
    if insufficient:
        quality_score -= 35
    if high_variance:
        quality_score -= 30
    if estimated_reads:
        quality_score -= 20
    quality_score = max(0, quality_score)

    summary = {
        "utility_account_id": account_id,
        "meter_id": meter_id,
        "event_id": event_id,
        "event_date": event_date,
        "avg_kw_reduced": round(float(avg_kw_reduced), 4),
        "max_kw_reduced": round(float(max_kw_reduced), 4),
        "responded_flag": responded_flag,
        "baseline_quality_score": quality_score,
        "insufficient_baseline_days": insufficient,
        "high_variance_baseline": high_variance,
        "estimated_reads_in_baseline": estimated_reads,
        "morning_adjustment_factor": round(adjustment_factor, 4),
        "total_cbl_kwh": round(interval_df["cbl_kwh"].sum(), 3),
        "total_actual_kwh": round(interval_df["actual_kwh"].sum(), 3),
        "total_reduction_kwh": round(interval_df["reduction_kwh"].sum(), 3),
    }
    return interval_df, summary


def compute_all(intervals: pd.DataFrame, dr_events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    customer_summaries: list[dict] = []

    grouped = intervals.groupby(["utility_account_id", "meter_id", "event_id"], sort=False)
    for (account_id, meter_id, event_id), group in grouped:
        group = group.sort_values("interval_ts")
        bounds = event_window_bounds(group)
        if not bounds:
            continue

        event_date = group["event_date"].iloc[0]
        _, summary = compute_cbl_for_customer_event(
            str(account_id),
            int(event_id),
            str(meter_id),
            event_date,
            group,
            bounds,
        )
        if summary:
            customer_summaries.append(summary)

    customer_df = pd.DataFrame(customer_summaries)
    if customer_df.empty:
        return customer_df, pd.DataFrame()

    event_summary = build_event_summary(customer_df, dr_events)
    output = customer_df.merge(
        event_summary[
            [
                "event_id",
                "total_mw_delivered",
                "participation_rate_pct",
                "avg_performance_pct",
                "customers_with_bad_baseline",
                "mw_called",
                "mw_delivered_iso",
            ]
        ],
        on="event_id",
        how="left",
    )
    return output, event_summary


def build_event_summary(customer_df: pd.DataFrame, dr_events: pd.DataFrame) -> pd.DataFrame:
    customer_df = customer_df.copy()
    customer_df["bad_baseline"] = (
        customer_df["insufficient_baseline_days"]
        | customer_df["high_variance_baseline"]
        | customer_df["estimated_reads_in_baseline"]
    )
    customer_df["performance_pct"] = np.where(
        customer_df["total_cbl_kwh"] > 0,
        100.0 * customer_df["total_reduction_kwh"] / customer_df["total_cbl_kwh"],
        np.nan,
    )

    agg = (
        customer_df.groupby("event_id", as_index=False)
        .agg(
            customers_in_event=("utility_account_id", "nunique"),
            responders=("responded_flag", "sum"),
            avg_kw_reduced=("avg_kw_reduced", "mean"),
            avg_performance_pct=("performance_pct", "mean"),
            customers_with_bad_baseline=("bad_baseline", "sum"),
            total_reduction_kwh=("total_reduction_kwh", "sum"),
        )
    )
    agg["participation_rate_pct"] = 100.0 * agg["responders"] / agg["customers_in_event"]
    # Event window is 2 hours (8 x 15-min intervals).
    agg["total_kw_delivered"] = agg["total_reduction_kwh"] / 2.0
    agg["total_mw_delivered"] = agg["total_kw_delivered"] / 1000.0

    event_dates = (
        customer_df.groupby("event_id", as_index=False)["event_date"]
        .min()
        .assign(event_date=lambda d: d["event_date"].dt.strftime("%Y-%m-%d"))
    )
    dr = dr_events[["event_id", "event_date", "mw_called", "mw_delivered"]].rename(
        columns={"mw_delivered": "mw_delivered_iso", "event_date": "event_date_iso"}
    )
    agg = agg.merge(event_dates, on="event_id", how="left")
    agg = agg.merge(dr, on="event_id", how="left")
    if "event_date_iso" in agg.columns:
        agg["event_date"] = agg["event_date"].fillna(agg["event_date_iso"])
        agg = agg.drop(columns=["event_date_iso"])
    return agg


def print_event_summary(event_summary: pd.DataFrame) -> None:
    print("\nPer-event CBL performance summary")
    print("-" * 96)
    cols = [
        "event_id",
        "event_date",
        "mw_called",
        "mw_delivered_iso",
        "total_mw_delivered",
        "participation_rate_pct",
        "avg_performance_pct",
        "customers_with_bad_baseline",
        "customers_in_event",
    ]
    display = event_summary.copy()
    for col in ["participation_rate_pct", "avg_performance_pct"]:
        if col in display.columns:
            display[col] = display[col].round(1)
    for col in ["total_mw_delivered", "mw_called", "mw_delivered_iso"]:
        if col in display.columns:
            display[col] = display[col].round(2)

    print(display[cols].to_string(index=False))


def main() -> None:
    intervals, dr_events = load_inputs()
    customer_cbl, event_summary = compute_all(intervals, dr_events)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    customer_cbl.to_parquet(OUTPUT_PATH, index=False)
    print(f"Saved CBL performance -> {OUTPUT_PATH}")
    print(f"Customer-event rows: {len(customer_cbl):,}")

    if not event_summary.empty:
        print_event_summary(event_summary)


if __name__ == "__main__":
    main()
