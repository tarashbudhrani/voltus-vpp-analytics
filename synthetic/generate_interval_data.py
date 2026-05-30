"""Generate 15-minute interval meter CSVs for DR events (utility portal export simulation)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
DB_PATH = PROJECT_ROOT / "db" / "voltus_internal.db"

PARTICIPANTS_PER_EVENT = 200
INTERVALS_PER_PARTICIPANT = 24
BASELINE_INTERVALS = 16
EVENT_INTERVALS = 8
INTERVAL_MINUTES = 15

RNG = np.random.default_rng(42)

# Interval files align to all operational DR events in voltus_internal.db.
EVENT_DATES: list[str] = []  # populated from dr_events at runtime
FALLBACK_START_TIMES: dict[str, tuple[int, int]] = {}


def load_event_metadata() -> list[dict]:
    query = """
        SELECT event_id, event_date, event_start_time
        FROM dr_events
        ORDER BY event_date
    """
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(query).fetchall()

    events: list[dict] = []
    for event_id, event_date, start_time in rows:
        hour, minute = start_time.split(":")
        events.append(
            {
                "event_date": event_date,
                "event_id": event_id,
                "start_hour": int(hour),
                "start_minute": int(minute),
            }
        )
    return events


def load_participant_accounts(limit: int = PARTICIPANTS_PER_EVENT) -> pd.DataFrame:
    query = """
        SELECT DISTINCT
            c.utility_account_number,
            c.utility_name,
            c.state
        FROM customers c
        INNER JOIN enrollments e ON e.voltus_customer_id = c.voltus_customer_id
        WHERE c.utility_account_number IS NOT NULL
          AND e.status IN ('active', 'pending', 'inactive')
        ORDER BY c.utility_account_number
        LIMIT ?
    """
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(query, conn, params=(limit,))
    return df


def utility_timezone(state: str, utility_name: str) -> str:
    if state == "IL" or utility_name in ("ComEd", "AmerenIL"):
        return "America/Chicago"
    return "America/New_York"


def assign_meters(accounts: pd.DataFrame) -> pd.DataFrame:
    """Some utility accounts have two meters (not 1-to-1 with account)."""
    records: list[dict] = []
    dual_meter_mask = RNG.random(len(accounts)) < 0.18

    for i, row in accounts.iterrows():
        account = str(row["utility_account_number"])
        records.append(
            {
                "utility_account_id": account,
                "meter_id": f"MTR-{account}-1",
                "utility_name": row["utility_name"],
                "state": row["state"],
            }
        )
        if dual_meter_mask[i]:
            records.append(
                {
                    "utility_account_id": account,
                    "meter_id": f"MTR-{account}-2",
                    "utility_name": row["utility_name"],
                    "state": row["state"],
                }
            )

    meters = pd.DataFrame(records)
    if len(meters) < PARTICIPANTS_PER_EVENT:
        raise ValueError("Not enough meter assignments for event participants")

    return meters.sample(n=PARTICIPANTS_PER_EVENT, random_state=42).reset_index(drop=True)


def baseline_usage_kwh(local_dt: datetime) -> float:
    hour = local_dt.hour + local_dt.minute / 60
    if 14 <= hour < 20:
        low, high = 0.8, 1.8
    else:
        low, high = 0.3, 1.0
    return round(float(RNG.uniform(low, high)), 3)


def generate_event_rows(event: dict, participants: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    event_date = datetime.strptime(event["event_date"], "%Y-%m-%d").date()
    event_start_local = datetime(
        event_date.year,
        event_date.month,
        event_date.day,
        event["start_hour"],
        event["start_minute"],
    )
    window_start_local = event_start_local - timedelta(hours=4)

    responder_mask = RNG.random(len(participants)) >= 0.30
    reduction_pct = RNG.uniform(0.20, 0.40, size=len(participants))

    rows: list[dict] = []
    for p_idx, participant in participants.iterrows():
        tz_name = utility_timezone(participant["state"], participant["utility_name"])
        tz = ZoneInfo(tz_name)

        for interval_idx in range(INTERVALS_PER_PARTICIPANT):
            local_naive = window_start_local + timedelta(minutes=INTERVAL_MINUTES * interval_idx)
            local_aware = local_naive.replace(tzinfo=tz)
            utc_dt = local_aware.astimezone(ZoneInfo("UTC"))

            is_event_window = interval_idx >= BASELINE_INTERVALS
            usage = baseline_usage_kwh(local_naive)

            if is_event_window and responder_mask[p_idx]:
                usage = round(usage * (1 - reduction_pct[p_idx]), 3)

            rows.append(
                {
                    "utility_account_id": participant["utility_account_id"],
                    "meter_id": participant["meter_id"],
                    "interval_start_local": local_naive.strftime("%Y-%m-%d %H:%M:%S"),
                    "interval_start_utc": utc_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "usage_kwh": usage,
                    "data_quality_flag": "A",
                    "event_id": event["event_id"],
                    "is_event_window": int(is_event_window),
                }
            )

    df = pd.DataFrame(rows)
    theoretical_rows = len(df)

    # 1) Omit ~4% of rows (meter comm failure).
    omit_count = int(round(theoretical_rows * 0.04))
    omit_indices = RNG.choice(df.index, size=omit_count, replace=False)
    df = df.drop(index=omit_indices).reset_index(drop=True)

    # 2) ~1% negative usage values (meter error).
    negative_count = max(1, int(round(len(df) * 0.01)))
    negative_indices = RNG.choice(df.index, size=negative_count, replace=False)
    df.loc[negative_indices, "usage_kwh"] = RNG.uniform(-0.3, -0.05, size=negative_count).round(3)

    # 3) interval_start_local already naive (no timezone indicator).

    # 4) ~15% missing interval_start_utc.
    missing_utc_count = int(round(len(df) * 0.15))
    missing_utc_indices = RNG.choice(df.index, size=missing_utc_count, replace=False)
    df.loc[missing_utc_indices, "interval_start_utc"] = np.nan

    # 6) ~6% estimated reads.
    estimated_count = int(round(len(df) * 0.06))
    estimated_indices = RNG.choice(df.index, size=estimated_count, replace=False)
    df.loc[estimated_indices, "data_quality_flag"] = "E"

    # 5) ~2% exact duplicate rows (portal resubmission).
    duplicate_count = int(round(theoretical_rows * 0.02))
    duplicate_samples = df.sample(n=duplicate_count, random_state=42).copy()
    df = pd.concat([df, duplicate_samples], ignore_index=True)

    stats = {
        "theoretical_rows": theoretical_rows,
        "missing_intervals": omit_count,
        "duplicates_added": duplicate_count,
        "rows_generated": len(df),
    }
    return df, stats


def output_path(event_date: str) -> Path:
    compact = event_date.replace("-", "")
    return RAW_DIR / f"interval_event_{compact}.csv"


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}. Run db/seed_database.py first.")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    accounts = load_participant_accounts(limit=500)

    events = load_event_metadata()
    print(f"Generating interval data for {len(events)} DR events\n")

    total_rows = 0
    for event in events:
        participants = assign_meters(accounts)
        df, stats = generate_event_rows(event, participants)

        path = output_path(event["event_date"])
        df.to_csv(path, index=False)

        total_rows += stats["rows_generated"]
        print(f"{path.name}")
        print(f"  rows generated:      {stats['rows_generated']:,}")
        print(f"  missing intervals:   {stats['missing_intervals']:,}")
        print(f"  duplicate rows:      {stats['duplicates_added']:,}")
        print()

    print(f"Total rows across all files: {total_rows:,}")


if __name__ == "__main__":
    main()
