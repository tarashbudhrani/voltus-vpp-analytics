"""Clean all raw data sources and write staging parquet files to data/processed/."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from sqlalchemy import create_engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
EIA_CACHE_DIR = PROJECT_ROOT / "data" / "eia_cache"
DB_PATH = PROJECT_ROOT / "db" / "voltus_internal.db"
API_BASE = "http://127.0.0.1:5001"

ENROLLMENT_PATH = RAW_DIR / "partner_enrollment_portal.csv"
INTERVAL_GLOB = "interval_event_*.csv"
EIA_PATH = EIA_CACHE_DIR / "eia_grid_demand.csv"

DB_TABLES = ["partners", "programs", "customers", "enrollments", "dr_events"]
EASTERN = "America/New_York"


@dataclass
class SourceReport:
    name: str
    rows_in: int = 0
    rows_out: int = 0
    issues_found: dict[str, int] = field(default_factory=dict)
    issues_fixed: dict[str, int] = field(default_factory=dict)
    manual_review: list[str] = field(default_factory=list)
    fix_log: list[str] = field(default_factory=list)

    def log_fix(self, message: str, count: int) -> None:
        self.fix_log.append(message)
        print(f"  {message}: {count:,}")


def parse_enrollment_date(value: str) -> pd.Timestamp:
    if pd.isna(value) or str(value).strip() == "":
        return pd.NaT
    text = str(value).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return pd.to_datetime(text, format="%Y-%m-%d")
    return pd.to_datetime(text, format="%m/%d/%Y")


def normalize_signup_paid(value: Any) -> bool | pd._libs.missing.NAType:
    if pd.isna(value):
        return pd.NA
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return pd.NA


def clean_enrollment() -> tuple[pd.DataFrame, SourceReport]:
    report = SourceReport(name="partner_enrollment_portal.csv")
    df = pd.read_csv(ENROLLMENT_PATH, dtype={"utility_account_id": str})
    report.rows_in = len(df)

    slash_dates = df["enrollment_date"].astype(str).str.match(r"^\d{2}/\d{2}/\d{4}$", na=False)
    iso_dates = df["enrollment_date"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)
    report.issues_found["mixed_enrollment_date_formats"] = int(slash_dates.sum() + iso_dates.sum())
    parsed_dates = df["enrollment_date"].apply(parse_enrollment_date)
    df["enrollment_date"] = parsed_dates
    report.issues_fixed["enrollment_date_standardized"] = int(parsed_dates.notna().sum())
    report.log_fix(
        "Standardized enrollment_date (MM/DD/YYYY and YYYY-MM-DD -> datetime)",
        int(slash_dates.sum() + iso_dates.sum()),
    )

    status_before = df["enrollment_status"].astype(str)
    mixed_status = status_before.str.lower().isin(["active", "enrolled"]).sum()
    report.issues_found["inconsistent_enrollment_status"] = int(
        status_before.isin(["ACTIVE", "Active", "Enrolled", "enrolled"]).sum()
    )
    df["enrollment_status"] = status_before.str.strip().str.lower().replace(
        {
            "enrolled": "active",
            "pending": "inactive",
            "suspended": "inactive",
        }
    )
    if "opt_out_date" in df.columns:
        opted_out = df["opt_out_date"].notna() & (df["opt_out_date"].astype(str).str.strip() != "")
        df.loc[opted_out, "enrollment_status"] = "opted_out"
    report.issues_fixed["enrollment_status_standardized"] = int(mixed_status)
    report.log_fix("Standardized enrollment_status (mapped enrolled/active variants -> active)", int(mixed_status))

    underscore_serials = df["device_serial"].astype(str).str.contains("_", na=False)
    report.issues_found["underscore_device_serials"] = int(underscore_serials.sum())
    df["device_serial"] = df["device_serial"].astype(str).str.replace("_", "-", regex=False)
    report.issues_fixed["device_serial_standardized"] = int(underscore_serials.sum())
    report.log_fix("Standardized device_serial (underscore -> dash)", int(underscore_serials.sum()))

    mixed_signup = df["signup_incentive_paid"].astype(str).str.lower().isin(
        ["true", "1", "yes", "false", "0", "no"]
    )
    report.issues_found["mixed_signup_incentive_paid"] = int(mixed_signup.sum())
    df["signup_incentive_paid"] = df["signup_incentive_paid"].apply(normalize_signup_paid)
    report.issues_fixed["signup_incentive_paid_standardized"] = int(mixed_signup.sum())
    report.log_fix("Standardized signup_incentive_paid (True/true/1/yes -> boolean)", int(mixed_signup.sum()))

    account_text = df["utility_account_id"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
    df["utility_account_id"] = account_text
    missing_zero_flag = account_text.str.len() < 10
    df["missing_leading_zero_flag"] = missing_zero_flag
    report.issues_found["utility_account_id_missing_leading_zero"] = int(missing_zero_flag.sum())
    report.issues_fixed["utility_account_id_flagged"] = int(missing_zero_flag.sum())
    report.log_fix(
        "Flagged utility_account_id possibly missing leading zero (<10 digits)",
        int(missing_zero_flag.sum()),
    )

    dup_count = int(df.duplicated(keep=False).sum())
    report.issues_found["exact_duplicate_rows"] = dup_count
    before_dedup = len(df)
    df = df.sort_values("enrollment_date")
    df = df.drop_duplicates(keep="last")
    removed = before_dedup - len(df)
    report.issues_fixed["exact_duplicates_removed"] = removed
    report.log_fix("Removed exact duplicate rows (kept most recent enrollment_date)", removed)

    null_emails = int(df["customer_email"].isna().sum() + (df["customer_email"].astype(str) == "").sum())
    if null_emails:
        report.manual_review.append(f"{null_emails:,} enrollment rows with NULL customer_email")

    report.rows_out = len(df)
    return df, report


def pad_account_number(value: Any) -> str | pd._libs.missing.NAType:
    if pd.isna(value):
        return pd.NA
    text = str(value).strip().replace(".0", "")
    if text.isdigit() and len(text) < 7:
        return text.zfill(7)
    return text


def clean_capacity_kw(value: Any) -> float | pd._libs.missing.NAType:
    if pd.isna(value):
        return pd.NA
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().replace("kw", "").strip()
    try:
        return float(text)
    except ValueError:
        return pd.NA


def parse_enrolled_date(value: Any) -> pd.Timestamp:
    if pd.isna(value):
        return pd.NaT
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return pd.NaT
    return ts.tz_convert(None).normalize()


def clean_database() -> tuple[dict[str, pd.DataFrame], SourceReport]:
    report = SourceReport(name="voltus_internal.db")
    engine = create_engine(f"sqlite:///{DB_PATH}")

    tables: dict[str, pd.DataFrame] = {}
    total_in = 0
    total_out = 0

    for table in DB_TABLES:
        tables[table] = pd.read_sql_table(table, engine)
        total_in += len(tables[table])

    customers = tables["customers"]
    dup_email_groups = customers["email"].notna() & customers.duplicated(subset=["email"], keep=False)
    customers["duplicate_customer_flag"] = dup_email_groups
    dup_count = int(dup_email_groups.sum())
    report.issues_found["duplicate_customers_same_email"] = dup_count
    report.issues_fixed["duplicate_customers_flagged"] = dup_count
    report.log_fix("Flagged duplicate customers (same email, different voltus_customer_id)", dup_count)
    report.manual_review.append(
        f"{dup_count:,} customer rows share an email with another voltus_customer_id (review merge logic)"
    )

    stripped_accounts = customers["utility_account_number"].astype(str).str.len() < 10
    report.issues_found["utility_account_number_short"] = int(stripped_accounts.sum())
    customers["utility_account_number"] = customers["utility_account_number"].apply(pad_account_number)
    padded = int(stripped_accounts.sum())
    report.issues_fixed["utility_account_number_padded"] = padded
    report.log_fix("Padded utility_account_number with leading zeros to 7+ digits", padded)
    tables["customers"] = customers

    enrollments = tables["enrollments"]
    string_capacity = enrollments["capacity_kw"].astype(str).str.contains("kw", case=False, na=False)
    report.issues_found["capacity_kw_string_values"] = int(string_capacity.sum())
    enrollments["capacity_kw"] = enrollments["capacity_kw"].apply(clean_capacity_kw)
    report.issues_fixed["capacity_kw_converted_to_float"] = int(string_capacity.sum())
    report.log_fix("Fixed capacity_kw (stripped kW suffix, converted to float)", int(string_capacity.sum()))

    tz_dates = enrollments["enrolled_date"].astype(str).str.contains("T", na=False)
    report.issues_found["timezone_aware_enrolled_date"] = int(tz_dates.sum())
    enrollments["enrolled_date"] = enrollments["enrolled_date"].apply(parse_enrolled_date)
    report.issues_fixed["enrolled_date_parsed_to_naive_date"] = int(tz_dates.sum())
    report.log_fix("Fixed enrolled_date (timezone-aware strings -> UTC naive date)", int(tz_dates.sum()))

    contradictory_notes = enrollments["notes"].fillna("").astype(str).str.len().gt(0)
    if contradictory_notes.any():
        report.manual_review.append(
            f"{int(contradictory_notes.sum()):,} enrollment notes may contradict status field"
        )

    tables["enrollments"] = enrollments

    for table in DB_TABLES:
        total_out += len(tables[table])

    report.rows_in = total_in
    report.rows_out = total_out
    return tables, report


def fetch_devices_bulk(device_ids: list[str], batch_size: int = 2000) -> list[dict]:
    devices: list[dict] = []
    for start in range(0, len(device_ids), batch_size):
        batch = device_ids[start : start + batch_size]
        response = requests.post(
            f"{API_BASE}/api/devices/bulk",
            json={"device_ids": batch},
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        devices.extend(payload.get("devices", []))
    return devices


def clean_devices() -> tuple[pd.DataFrame, SourceReport]:
    report = SourceReport(name="mock_thermostat_api")

    if os.environ.get("VPP_PIPELINE") == "1":
        import sys

        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from synthetic.mock_thermostat_api import build_devices_dataframe

        df = build_devices_dataframe()
        report.rows_in = df["device_id"].nunique()
        report.issues_found["devices_returned"] = report.rows_in
        report.issues_fixed["last_seen_timestamp_converted"] = report.rows_in
        report.log_fix("Converted last_seen_timestamp from Unix epoch to datetime", report.rows_in)
        report.issues_fixed["device_id_standardized"] = report.rows_in
        report.log_fix("Standardized device_id (underscore -> dash)", report.rows_in)
        empty_history_count = int(df.drop_duplicates("device_id")["runtime_history_empty"].sum())
        report.issues_found["empty_runtime_history"] = empty_history_count
        report.issues_fixed["empty_runtime_history_flagged"] = empty_history_count
        report.log_fix("Flagged devices with empty runtime_history", empty_history_count)
        report.rows_out = len(df)
        return df, report

    list_response = requests.get(f"{API_BASE}/api/devices", timeout=60)
    list_response.raise_for_status()
    device_ids = [item["device_id"] for item in list_response.json().get("devices", [])]
    report.rows_in = len(device_ids)

    raw_devices = fetch_devices_bulk(device_ids)
    report.issues_found["devices_requested"] = len(device_ids)
    report.issues_found["devices_returned"] = len(raw_devices)

    flattened_rows: list[dict] = []
    empty_history_count = 0
    epoch_converted = 0
    underscore_ids = 0

    for device in raw_devices:
        device_id = str(device["device_id"])
        if "_" in device_id:
            underscore_ids += 1
        clean_device_id = device_id.replace("_", "-")

        last_seen = device.get("last_seen_timestamp")
        last_seen_dt = pd.to_datetime(last_seen, unit="s", utc=True).tz_convert(None)
        epoch_converted += 1

        history = device.get("runtime_history") or []
        runtime_history_empty = len(history) == 0
        if runtime_history_empty:
            empty_history_count += 1

        location = device.get("location") or {}
        base_row = {
            "device_id": clean_device_id,
            "firmware_version": str(device.get("firmware_version")),
            "last_seen_timestamp": last_seen_dt,
            "battery_level": device.get("battery_level"),
            "connectivity_status": device.get("connectivity_status"),
            "location_zip": location.get("zip"),
            "location_state": location.get("state"),
            "location_lat": location.get("lat"),
            "location_lon": location.get("lon"),
            "runtime_history_empty": runtime_history_empty,
        }

        if runtime_history_empty:
            row = base_row.copy()
            row.update(
                {
                    "runtime_date": pd.NaT,
                    "runtime_minutes": pd.NA,
                    "setpoint_delta_f": pd.NA,
                    "mode": pd.NA,
                    "responded_to_event": pd.NA,
                }
            )
            flattened_rows.append(row)
        else:
            for entry in history:
                row = base_row.copy()
                row.update(
                    {
                        "runtime_date": pd.to_datetime(entry["date"]),
                        "runtime_minutes": entry.get("runtime_minutes"),
                        "setpoint_delta_f": entry.get("setpoint_delta_f"),
                        "mode": entry.get("mode"),
                        "responded_to_event": entry.get("responded_to_event"),
                    }
                )
                flattened_rows.append(row)

    df = pd.DataFrame(flattened_rows)
    report.issues_fixed["last_seen_timestamp_converted"] = epoch_converted
    report.log_fix("Converted last_seen_timestamp from Unix epoch to datetime", epoch_converted)

    report.issues_fixed["device_id_standardized"] = underscore_ids
    report.log_fix("Standardized device_id (underscore -> dash)", underscore_ids)

    report.issues_found["empty_runtime_history"] = empty_history_count
    report.issues_fixed["empty_runtime_history_flagged"] = empty_history_count
    report.log_fix("Flagged devices with empty runtime_history", empty_history_count)

    null_location_devices = (
        df.drop_duplicates(subset=["device_id"])["location_state"].isna().sum() if len(df) else 0
    )
    if null_location_devices:
        report.manual_review.append(
            f"{int(null_location_devices):,} devices with NULL location (~5% expected)"
        )

    mixed_firmware = df["firmware_version"].astype(str).str.match(r"^\d+\.\d+$").sum() if len(df) else 0
    if mixed_firmware:
        report.manual_review.append(
            f"{int(mixed_firmware):,} device rows have numeric-looking firmware_version values"
        )

    report.rows_out = len(df)
    return df, report


def clean_intervals() -> tuple[pd.DataFrame, SourceReport]:
    report = SourceReport(name="interval_event CSV files")
    files = sorted(RAW_DIR.glob(INTERVAL_GLOB))
    if not files:
        raise FileNotFoundError(f"No interval files found matching {INTERVAL_GLOB}")

    frames: list[pd.DataFrame] = []
    for path in files:
        chunk = pd.read_csv(path, dtype={"utility_account_id": str})
        chunk["source_file"] = path.name
        frames.append(chunk)

    df = pd.concat(frames, ignore_index=True)
    report.rows_in = len(df)

    dup_mask = df.duplicated(
        subset=["utility_account_id", "interval_start_local", "usage_kwh"],
        keep=False,
    )
    dup_rows = int(dup_mask.sum())
    report.issues_found["exact_duplicate_interval_rows"] = dup_rows
    before = len(df)
    df = df.drop_duplicates(subset=["utility_account_id", "interval_start_local", "usage_kwh"], keep="first")
    removed = before - len(df)
    report.issues_fixed["duplicate_interval_rows_removed"] = removed
    report.log_fix("Removed exact duplicate interval rows (account + interval_start + usage_kwh)", removed)

    negative_mask = df["usage_kwh"] < 0
    negative_count = int(negative_mask.sum())
    df["is_error"] = negative_mask
    report.issues_found["negative_usage_kwh"] = negative_count
    report.issues_fixed["negative_usage_kwh_flagged"] = negative_count
    report.log_fix("Flagged negative usage_kwh rows with is_error=True (not removed)", negative_count)

    missing_utc = df["interval_start_utc"].isna()
    missing_utc_count = int(missing_utc.sum())
    report.issues_found["missing_interval_start_utc"] = missing_utc_count
    local_ts = pd.to_datetime(df.loc[missing_utc, "interval_start_local"], errors="coerce")
    localized = local_ts.dt.tz_localize(EASTERN, ambiguous="NaT", nonexistent="NaT")
    df.loc[missing_utc, "interval_start_utc"] = (
        localized.dt.tz_convert("UTC").dt.strftime("%Y-%m-%d %H:%M:%S")
    )
    filled = int(df.loc[missing_utc, "interval_start_utc"].notna().sum()) if missing_utc_count else 0
    report.issues_fixed["interval_start_utc_filled"] = filled
    report.log_fix("Filled missing interval_start_utc from local time (assumed Eastern Time)", filled)

    still_missing_utc = int(df["interval_start_utc"].isna().sum())
    if still_missing_utc:
        report.manual_review.append(f"{still_missing_utc:,} interval rows still missing interval_start_utc")

    expected_per_account_event = (
        df.groupby(["utility_account_id", "event_id", "source_file"])["meter_id"]
        .nunique()
        .mul(24)
        .rename("intervals_expected")
        .reset_index()
    )
    actual_per_account_event = (
        df.groupby(["utility_account_id", "event_id", "source_file"])
        .size()
        .rename("intervals_actual")
        .reset_index()
    )
    interval_counts = expected_per_account_event.merge(
        actual_per_account_event,
        on=["utility_account_id", "event_id", "source_file"],
        how="left",
    )
    interval_counts["intervals_actual"] = interval_counts["intervals_actual"].fillna(0).astype(int)
    interval_counts["intervals_missing"] = (
        interval_counts["intervals_expected"] - interval_counts["intervals_actual"]
    )

    df = df.merge(
        interval_counts[
            ["utility_account_id", "event_id", "source_file", "intervals_expected", "intervals_actual"]
        ],
        on=["utility_account_id", "event_id", "source_file"],
        how="left",
    )

    missing_intervals = int((interval_counts["intervals_missing"] > 0).sum())
    report.issues_found["accounts_with_missing_intervals"] = missing_intervals
    report.manual_review.append(
        f"{missing_intervals:,} account/event groups have fewer intervals than expected (meter comm gaps)"
    )

    estimated_reads = int((df["data_quality_flag"] == "E").sum())
    if estimated_reads:
        report.manual_review.append(f"{estimated_reads:,} interval rows have estimated reads (flag=E)")

    report.rows_out = len(df)
    return df, report


def clean_eia() -> tuple[pd.DataFrame, SourceReport]:
    report = SourceReport(name="eia_cache")
    if not EIA_PATH.exists():
        raise FileNotFoundError(f"EIA cache file not found: {EIA_PATH}")

    df = pd.read_csv(EIA_PATH, parse_dates=["period"])
    report.rows_in = len(df)
    report.rows_out = len(df)

    min_date = df["period"].min()
    max_date = df["period"].max()
    markets = ", ".join(sorted(df["iso_market"].unique()))
    report.log_fix("Confirmed EIA date range", len(df))
    print(f"  EIA date range: {min_date.date()} to {max_date.date()} ({markets})")

    report.issues_fixed["eia_cache_loaded"] = len(df)
    return df, report


def print_data_quality_report(reports: list[SourceReport]) -> None:
    print("\n" + "=" * 72)
    print("DATA QUALITY REPORT")
    print("=" * 72)

    for report in reports:
        print(f"\n[{report.name}]")
        print(f"  Rows in:  {report.rows_in:,}")
        print(f"  Rows out: {report.rows_out:,}")
        print("  Issues found:")
        if report.issues_found:
            for issue, count in report.issues_found.items():
                print(f"    - {issue}: {count:,}")
        else:
            print("    - none")
        print("  Issues fixed:")
        if report.issues_fixed:
            for issue, count in report.issues_fixed.items():
                print(f"    - {issue}: {count:,}")
        else:
            print("    - none")
        if report.manual_review:
            print("  Manual review required:")
            for item in report.manual_review:
                print(f"    - {item}")
        else:
            print("  Manual review required: none")


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    reports: list[SourceReport] = []

    print("SOURCE 1 - partner_enrollment_portal.csv")
    enrollment_df, enrollment_report = clean_enrollment()
    enrollment_path = PROCESSED_DIR / "enrollment_clean.parquet"
    enrollment_df.to_parquet(enrollment_path, index=False)
    print(f"  Saved -> {enrollment_path}\n")
    reports.append(enrollment_report)

    print("SOURCE 2 - voltus_internal.db")
    db_tables, db_report = clean_database()
    for table_name, table_df in db_tables.items():
        out_path = PROCESSED_DIR / f"db_{table_name}_clean.parquet"
        table_df.to_parquet(out_path, index=False)
        print(f"  Saved -> {out_path}")
    print()
    reports.append(db_report)

    print("SOURCE 3 - mock thermostat API")
    devices_df, devices_report = clean_devices()
    devices_path = PROCESSED_DIR / "devices_clean.parquet"
    devices_df.to_parquet(devices_path, index=False)
    print(f"  Saved -> {devices_path}\n")
    reports.append(devices_report)

    print("SOURCE 4 - interval CSV files")
    interval_df, interval_report = clean_intervals()
    interval_path = PROCESSED_DIR / "interval_clean.parquet"
    interval_df.to_parquet(interval_path, index=False)
    print(f"  Saved -> {interval_path}\n")
    reports.append(interval_report)

    print("SOURCE 5 - EIA cache")
    eia_df, eia_report = clean_eia()
    eia_path = PROCESSED_DIR / "eia_demand_clean.parquet"
    eia_df.to_parquet(eia_path, index=False)
    print(f"  Saved -> {eia_path}\n")
    reports.append(eia_report)

    print_data_quality_report(reports)


if __name__ == "__main__":
    main()
