"""Link all cleaned sources into a unified VPP master entity table."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_PATH = PROCESSED_DIR / "vpp_master.parquet"

INTERVAL_HOURS = 0.25
SUMMER_START = pd.Timestamp("2024-06-01")
SUMMER_END = pd.Timestamp("2024-09-30")


def load_processed(name: str) -> pd.DataFrame:
    path = PROCESSED_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing cleaned file: {path}")
    return pd.read_parquet(path)


def normalize_account(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip().replace(".0", "")
    return text or None


def account_lookup_keys(value: object) -> dict[str, str | None]:
    base = normalize_account(value)
    if base is None:
        return {"exact": None, "padded10": None, "stripped": None}
    stripped = base.lstrip("0") or "0"
    return {
        "exact": base,
        "padded10": base.zfill(10) if base.isdigit() else base,
        "stripped": stripped,
    }


def build_customer_lookup(customers: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for _, row in customers.iterrows():
        keys = account_lookup_keys(row["utility_account_number"])
        payload = {
            "voltus_customer_id": row["voltus_customer_id"],
            "utility_account_number": normalize_account(row["utility_account_number"]),
            "utility_name_db": row["utility_name"],
            "customer_email_db": row["email"],
        }
        for match_type, key in keys.items():
            if key:
                rows.append({"match_key": key, "match_type": match_type, **payload})
    lookup = pd.DataFrame(rows)
    lookup = lookup.drop_duplicates(subset=["match_key", "voltus_customer_id"], keep="first")
    return lookup


def link_enrollment_to_customers(
    enrollment: pd.DataFrame, customers: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, float | int]]:
    lookup = build_customer_lookup(customers)
    exact_lookup = lookup[lookup["match_type"] == "exact"].drop_duplicates("match_key")
    padded_lookup = lookup[lookup["match_type"] == "padded10"].drop_duplicates("match_key")
    stripped_lookup = lookup[lookup["match_type"] == "stripped"].drop_duplicates("match_key")

    master = enrollment.copy()
    master["utility_account_id"] = master["utility_account_id"].apply(normalize_account)

    exact = master.merge(
        exact_lookup,
        left_on="utility_account_id",
        right_on="match_key",
        how="left",
        suffixes=("", "_cust"),
    )
    exact["match_confidence"] = np.where(
        exact["voltus_customer_id"].notna(), "exact", None
    )

    unmatched = exact["voltus_customer_id"].isna()
    padded = master.loc[unmatched, ["utility_account_id"]].copy()
    padded["padded_key"] = padded["utility_account_id"].apply(
        lambda x: account_lookup_keys(x)["padded10"]
    )
    padded_match = padded.merge(
        padded_lookup,
        left_on="padded_key",
        right_on="match_key",
        how="left",
    )
    for col in ["voltus_customer_id", "utility_account_number", "utility_name_db", "customer_email_db"]:
        exact.loc[unmatched, col] = padded_match[col].values
    padded_fixed = unmatched & exact["voltus_customer_id"].notna()
    exact.loc[padded_fixed, "match_confidence"] = "padded_zero_fix"

    still_unmatched = exact["voltus_customer_id"].isna()
    stripped = master.loc[still_unmatched, ["utility_account_id"]].copy()
    stripped["stripped_key"] = stripped["utility_account_id"].apply(
        lambda x: account_lookup_keys(x)["stripped"]
    )
    stripped_match = stripped.merge(
        stripped_lookup,
        left_on="stripped_key",
        right_on="match_key",
        how="left",
    )
    for col in ["voltus_customer_id", "utility_account_number", "utility_name_db", "customer_email_db"]:
        exact.loc[still_unmatched, col] = stripped_match[col].values
    stripped_fixed = still_unmatched & exact["voltus_customer_id"].notna()
    exact.loc[stripped_fixed, "match_confidence"] = "padded_zero_fix"

    exact["match_confidence"] = exact["match_confidence"].fillna("unmatched")
    exact["link_account_id"] = exact["utility_account_number"].fillna(exact["utility_account_id"])

    matched = int((exact["match_confidence"] != "unmatched").sum())
    unmatched_count = int((exact["match_confidence"] == "unmatched").sum())
    print("STEP 1 - Link enrollment CSV to internal customer DB")
    print(f"  Rows matched: {matched:,}")
    print(f"  Rows not matched: {unmatched_count:,}")
    print(f"    exact: {(exact['match_confidence'] == 'exact').sum():,}")
    print(f"    padded_zero_fix: {(exact['match_confidence'] == 'padded_zero_fix').sum():,}")

    stats = {
        "rows_in": len(enrollment),
        "matched": matched,
        "unmatched": unmatched_count,
        "match_rate": matched / len(enrollment) if len(enrollment) else 0,
    }
    return exact, stats


def link_programs(master: pd.DataFrame, db_enrollments: pd.DataFrame, programs: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    db_enrollments = db_enrollments.sort_values("enrolled_date").drop_duplicates(
        subset=["voltus_customer_id"], keep="last"
    )
    join_cols = [
        "voltus_customer_id",
        "enrollment_id",
        "program_id",
        "partner_id",
        "enrolled_date",
        "status",
        "capacity_kw",
        "program_name",
        "program_type",
        "capacity_rate_per_kw",
    ]
    program_lookup = programs[
        ["program_id", "program_name", "program_type", "capacity_rate_per_kw"]
    ].drop_duplicates("program_id")
    db_enriched = db_enrollments.merge(program_lookup, on="program_id", how="left")
    before = len(master)
    linked = master.merge(
        db_enriched[join_cols],
        on="voltus_customer_id",
        how="left",
        suffixes=("_portal", "_db"),
    )

    matched = int(linked["program_id"].notna().sum())
    print("\nSTEP 2 - Link internal DB enrollments to programs")
    print(f"  Enrollments with program details: {matched:,} / {before:,}")
    print(f"  Match rate: {matched / before:.1%}")

    stats = {
        "rows_in": before,
        "matched": matched,
        "match_rate": matched / before if before else 0,
    }
    return linked, stats


def summarize_devices(devices: pd.DataFrame) -> pd.DataFrame:
    runtime = devices[devices["runtime_minutes"].notna()].copy()
    summary = (
        devices.groupby("device_id", as_index=False)
        .agg(
            device_last_seen=("last_seen_timestamp", "max"),
            runtime_history_empty=("runtime_history_empty", "max"),
        )
    )
    runtime_avg = (
        runtime.groupby("device_id", as_index=False)["runtime_minutes"]
        .mean()
        .rename(columns={"runtime_minutes": "runtime_30day_avg"})
    )
    return summary.merge(runtime_avg, on="device_id", how="left")


def link_devices(master: pd.DataFrame, devices: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    device_summary = summarize_devices(devices)
    before = len(master)
    linked = master.merge(
        device_summary,
        left_on="device_serial",
        right_on="device_id",
        how="left",
    )
    linked["device_unmatched"] = linked["device_last_seen"].isna()

    matched = int((~linked["device_unmatched"]).sum())
    print("\nSTEP 3 - Link to device API data")
    print(f"  Devices matched: {matched:,} / {before:,}")
    print(f"  Match rate: {matched / before:.1%}")
    print(f"  Unmatched devices flagged: {int(linked['device_unmatched'].sum()):,}")

    stats = {
        "rows_in": before,
        "matched": matched,
        "match_rate": matched / before if before else 0,
    }
    return linked, stats


def summarize_intervals(intervals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    usable = intervals[~intervals["is_error"].fillna(False)].copy()
    usable["is_event_window"] = usable["is_event_window"].astype(int)

    records: list[dict] = []
    for (account_id, event_id), group in usable.groupby(["utility_account_id", "event_id"]):
        summary = _summarize_account_event(group)
        records.append(
            {
                "utility_account_id": account_id,
                "event_id": event_id,
                **summary.to_dict(),
            }
        )

    event_summary = pd.DataFrame(records)
    if event_summary.empty:
        account_summary = pd.DataFrame(
            columns=[
                "utility_account_id",
                "events_participated",
                "avg_kw_reduced_per_event",
                "total_event_usage_kwh",
                "total_baseline_usage_kwh",
            ]
        )
        return event_summary, account_summary

    account_summary = (
        event_summary.groupby("utility_account_id", as_index=False)
        .agg(
            events_participated=("event_id", "nunique"),
            avg_kw_reduced_per_event=("kw_reduced", "mean"),
            total_event_usage_kwh=("event_usage_kwh", "sum"),
            total_baseline_usage_kwh=("baseline_usage_kwh", "sum"),
        )
    )
    return event_summary, account_summary


def _summarize_account_event(group: pd.DataFrame) -> pd.Series:
    baseline = group[group["is_event_window"] == 0]
    event = group[group["is_event_window"] == 1]

    baseline_kwh = baseline["usage_kwh"].sum()
    event_kwh = event["usage_kwh"].sum()
    baseline_intervals = len(baseline)
    event_intervals = len(event)

    baseline_kw = baseline_kwh / (baseline_intervals * INTERVAL_HOURS) if baseline_intervals else np.nan
    event_kw = event_kwh / (event_intervals * INTERVAL_HOURS) if event_intervals else np.nan
    kw_reduced = baseline_kw - event_kw if pd.notna(baseline_kw) and pd.notna(event_kw) else np.nan

    return pd.Series(
        {
            "baseline_usage_kwh": baseline_kwh,
            "event_usage_kwh": event_kwh,
            "baseline_kw": baseline_kw,
            "event_kw": event_kw,
            "kw_reduced": kw_reduced,
        }
    )


def link_intervals(master: pd.DataFrame, intervals: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    _, account_summary = summarize_intervals(intervals)
    before = len(master)
    linked = master.merge(
        account_summary,
        left_on="link_account_id",
        right_on="utility_account_id",
        how="left",
    )
    if "utility_account_id_interval" in linked.columns:
        linked = linked.drop(columns=["utility_account_id_interval"])
    elif "utility_account_id_y" in linked.columns:
        linked = linked.drop(columns=["utility_account_id_y"]).rename(
            columns={"utility_account_id_x": "utility_account_id"}
        )

    matched = int(linked["events_participated"].notna().sum())
    print("\nSTEP 4 - Link to interval meter data")
    print(f"  Enrollments with interval summary: {matched:,} / {before:,}")
    print(f"  Match rate: {matched / before:.1%}")

    stats = {
        "rows_in": before,
        "matched": matched,
        "match_rate": matched / before if before else 0,
    }
    return linked, stats


def prepare_eia_features(eia: pd.DataFrame, dr_events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    eia = eia.copy()
    eia["period"] = pd.to_datetime(eia["period"])
    summer = eia[(eia["period"] >= SUMMER_START) & (eia["period"] <= SUMMER_END)]
    peak_threshold = summer.groupby("iso_market")["demand_mwh"].quantile(0.90).rename("peak_threshold")

    eia = eia.merge(peak_threshold, on="iso_market", how="left")
    eia["was_peak_demand_hour"] = eia["demand_mwh"] >= eia["peak_threshold"]
    eia["event_date"] = eia["period"].dt.strftime("%Y-%m-%d")

    event_dates = dr_events[["event_id", "event_date", "iso_market"]].copy()
    event_eia = event_dates.merge(
        eia[["event_date", "iso_market", "demand_mwh", "was_peak_demand_hour"]],
        on=["event_date", "iso_market"],
        how="left",
    ).rename(columns={"demand_mwh": "grid_demand_at_event_mwh"})

    iso_dispatch = (
        event_eia.groupby("iso_market", as_index=False)
        .agg(grid_demand_at_dispatch=("grid_demand_at_event_mwh", "mean"))
    )
    return event_eia, iso_dispatch


def link_eia(
    master: pd.DataFrame, eia: pd.DataFrame, dr_events: pd.DataFrame, event_summary: pd.DataFrame
) -> tuple[pd.DataFrame, dict]:
    event_eia, iso_dispatch = prepare_eia_features(eia, dr_events)

    if event_summary.empty:
        participation = master[["link_account_id", "iso_market"]].copy()
        participation["grid_demand_at_event_mwh"] = pd.NA
        participation["was_peak_demand_hour"] = pd.NA
    else:
        participation = master[["link_account_id", "iso_market"]].merge(
            event_summary[["utility_account_id", "event_id"]],
            left_on="link_account_id",
            right_on="utility_account_id",
            how="left",
        )
        participation = participation.merge(
            event_eia[["event_id", "grid_demand_at_event_mwh", "was_peak_demand_hour"]],
            on="event_id",
            how="left",
        )

    participation["was_peak_demand_hour"] = (
        participation["was_peak_demand_hour"].fillna(False).astype(int)
    )
    account_dispatch = (
        participation.groupby("link_account_id", as_index=False)
        .agg(
            grid_demand_at_dispatch=("grid_demand_at_event_mwh", "mean"),
            peak_dispatch_events=("was_peak_demand_hour", "sum"),
        )
    )

    before = len(master)
    linked = master.merge(account_dispatch, on="link_account_id", how="left")
    linked = linked.merge(iso_dispatch, on="iso_market", how="left", suffixes=("", "_iso_fallback"))
    linked["grid_demand_at_dispatch"] = linked["grid_demand_at_dispatch"].fillna(
        linked["grid_demand_at_dispatch_iso_fallback"]
    )
    linked = linked.drop(columns=["grid_demand_at_dispatch_iso_fallback"])

    matched = int(linked["grid_demand_at_dispatch"].notna().sum())
    print("\nSTEP 5 - Link to EIA grid demand")
    print(f"  Rows with grid demand context: {matched:,} / {before:,}")
    print(f"  Match rate: {matched / before:.1%}")

    stats = {
        "rows_in": before,
        "matched": matched,
        "match_rate": matched / before if before else 0,
    }
    return linked, stats


def derive_funnel_stage(row: pd.Series) -> str:
    if row.get("match_confidence") == "unmatched":
        if bool(row.get("device_unmatched")):
            return "portal_only"
        events = row.get("events_participated")
        if pd.notna(events) and events > 0:
            return "active_participant"
        return "device_linked"
    if bool(row.get("device_unmatched")):
        return "enrolled_no_device"
    events = row.get("events_participated")
    if pd.isna(events) or events == 0:
        return "device_linked"
    return "active_participant"


def build_master_table(
    master: pd.DataFrame,
) -> pd.DataFrame:
    master["enrollment_funnel_stage"] = master.apply(derive_funnel_stage, axis=1)

    output = master.rename(
        columns={
            "status": "enrollment_status_db",
            "enrollment_status": "enrollment_status_portal",
        }
    )
    output["enrollment_status"] = output["enrollment_status_db"].fillna(
        output["enrollment_status_portal"]
    )
    output["enrolled_date"] = output["enrolled_date"]
    output["capacity_kw"] = output["capacity_kw"]

    columns = [
        "voltus_customer_id",
        "device_serial",
        "partner_name",
        "utility_zone",
        "iso_market",
        "program_name",
        "enrollment_status",
        "enrolled_date",
        "thermostat_model",
        "capacity_kw",
        "events_participated",
        "avg_kw_reduced_per_event",
        "enrollment_funnel_stage",
        "device_last_seen",
        "runtime_30day_avg",
        "grid_demand_at_dispatch",
        "match_confidence",
        "device_unmatched",
        "utility_account_id",
        "link_account_id",
        "customer_email",
        "program_id",
        "program_type",
        "peak_dispatch_events",
    ]
    for col in columns:
        if col not in output.columns:
            output[col] = pd.NA

    return output[columns]


def expand_master_to_event_grain(master: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    """One row per matched customer per event for downstream analytics/tests."""
    participation = (
        intervals.groupby(["utility_account_id", "event_id"], as_index=False)
        .size()
        .rename(columns={"size": "interval_rows"})
    )
    event_master = master.merge(
        participation,
        left_on="link_account_id",
        right_on="utility_account_id",
        how="inner",
        suffixes=("", "_interval"),
    )
    if "event_id_interval" in event_master.columns:
        event_master["event_id"] = event_master["event_id_interval"]
    event_master = event_master[event_master["voltus_customer_id"].notna()]
    event_master = event_master.drop_duplicates(subset=["voltus_customer_id", "event_id"], keep="last")
    return event_master


def print_final_summary(
    master: pd.DataFrame,
    step_stats: dict[str, dict],
) -> None:
    print("\n" + "=" * 72)
    print("FINAL JOIN SUMMARY")
    print("=" * 72)
    print(f"Total rows in master: {len(master):,}")

    print("\nMatch rates by step:")
    for step, stats in step_stats.items():
        print(f"  {step}: {stats['matched']:,} / {stats['rows_in']:,} ({stats['match_rate']:.1%})")

    print("\nData loss notes:")
    customer_unmatched = int((master["match_confidence"] == "unmatched").sum())
    if customer_unmatched:
        print(
            f"  - {customer_unmatched:,} portal enrollments could not be linked to internal "
            "customers (utility account mismatch despite zero-padding fixes)."
        )

    device_unmatched = int(master["device_unmatched"].sum())
    if device_unmatched:
        print(
            f"  - {device_unmatched:,} enrollments have no thermostat API match "
            "(device not returned by partner API bulk fetch)."
        )

    no_intervals = int(master["events_participated"].isna().sum())
    if no_intervals:
        print(
            f"  - {no_intervals:,} enrollments have no interval meter summary "
            "(account absent from post-event utility downloads)."
        )

    funnel = master["enrollment_funnel_stage"].value_counts()
    print("\nEnrollment funnel stages:")
    for stage, count in funnel.items():
        print(f"  - {stage}: {count:,}")


def main() -> None:
    print("Loading cleaned parquet files...")
    enrollment = load_processed("enrollment_clean.parquet")
    customers = load_processed("db_customers_clean.parquet")
    db_enrollments = load_processed("db_enrollments_clean.parquet")
    programs = load_processed("db_programs_clean.parquet")
    devices = load_processed("devices_clean.parquet")
    intervals = load_processed("interval_clean.parquet")
    eia = load_processed("eia_demand_clean.parquet")
    dr_events = load_processed("db_dr_events_clean.parquet")

    step_stats: dict[str, dict] = {}

    master, step_stats["step1_customer"] = link_enrollment_to_customers(enrollment, customers)
    master, step_stats["step2_programs"] = link_programs(master, db_enrollments, programs)
    master, step_stats["step3_devices"] = link_devices(master, devices)

    event_summary, _ = summarize_intervals(intervals)
    master, step_stats["step4_intervals"] = link_intervals(master, intervals)
    master, step_stats["step5_eia"] = link_eia(master, eia, dr_events, event_summary)

    master = build_master_table(master)
    master = expand_master_to_event_grain(master, intervals)
    master.to_parquet(OUTPUT_PATH, index=False)
    print(f"\nSaved master table -> {OUTPUT_PATH}")

    print_final_summary(master, step_stats)


if __name__ == "__main__":
    main()
