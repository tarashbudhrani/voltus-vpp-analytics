"""Generate partner enrollment portal CSV with intentional data quality issues."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "raw" / "partner_enrollment_portal.csv"

PARTNERS = {
    "Resideo": {
        "prefix": "RSO",
        "models": ["Honeywell T9", "Honeywell T6 Pro"],
    },
    "Google Nest": {
        "prefix": "NEST",
        "models": ["Nest Learning 4th Gen", "Nest Thermostat E"],
    },
    "ecobee": {
        "prefix": "ECO",
        "models": ["ecobee SmartThermostat", "ecobee3 lite"],
    },
}

UTILITY_ZONES = {
    "ComEd": {"iso_market": "PJM", "signup": 25, "annual": 10},
    "PPL": {"iso_market": "PJM", "signup": 30, "annual": 15},
    "PECO": {"iso_market": "PJM", "signup": 25, "annual": 12},
    "PSEG-LI": {"iso_market": "NYISO", "signup": 50, "annual": 35},
    "AmerenIL": {"iso_market": "MISO", "signup": 20, "annual": 10},
}

ENROLLMENT_STATUSES = ["active", "Active", "ACTIVE", "enrolled", "Enrolled"]
SIGNUP_PAID_VALUES = ["True", "true", "TRUE", "1", "yes"]
DATE_START = datetime(2023, 1, 1)
DATE_END = datetime(2025, 3, 1)

TOTAL_ROWS = 8000
ACCOUNT_POOL_SIZE = 6500
HIGH_MATCH_ROWS = 6800
RNG = np.random.default_rng(42)
fake = Faker()
Faker.seed(42)
random.seed(42)


def random_enrollment_date() -> datetime:
    delta_days = (DATE_END - DATE_START).days
    offset = int(RNG.integers(0, delta_days + 1))
    return DATE_START + timedelta(days=offset)


def format_enrollment_date(dt: datetime, use_iso: bool) -> str:
    if use_iso:
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%m/%d/%Y")


def generate_device_serial(prefix: str, use_underscore: bool) -> str:
    suffix = "".join(str(d) for d in RNG.integers(0, 10, size=5))
    sep = "_" if use_underscore else "-"
    return f"{prefix}{sep}{suffix}"


def generate_utility_account_id(strip_leading_zero: bool) -> str | int:
    if strip_leading_zero:
        # Originally 0-prefixed; leading zero dropped when stored as integer.
        return int(RNG.integers(10_000_000, 999_999_999))
    digits = RNG.integers(0, 10, size=10)
    return "".join(str(d) for d in digits)


def generate_row(
    *,
    partner_name: str,
    customer_email: str | None,
    utility_zone: str,
    opted_out: bool,
    strip_account_zero: bool,
    use_underscore_serial: bool,
    use_iso_date: bool,
    utility_account_id: str | int | None = None,
) -> dict:
    partner = PARTNERS[partner_name]
    zone = UTILITY_ZONES[utility_zone]
    enrollment_dt = random_enrollment_date()

    opt_out_date = ""
    if opted_out:
        opt_out_offset = int(RNG.integers(30, 400))
        opt_out_dt = enrollment_dt + timedelta(days=opt_out_offset)
        if opt_out_dt > DATE_END:
            opt_out_dt = DATE_END
        opt_out_date = opt_out_dt.strftime("%Y-%m-%d")

    signup_paid = RNG.choice(SIGNUP_PAID_VALUES)
    annual_paid = bool(RNG.choice([True, False], p=[0.7, 0.3]))

    return {
        "device_serial": generate_device_serial(partner["prefix"], use_underscore_serial),
        "partner_name": partner_name,
        "customer_email": customer_email,
        "utility_account_id": utility_account_id
        if utility_account_id is not None
        else generate_utility_account_id(strip_account_zero),
        "utility_zone": utility_zone,
        "iso_market": zone["iso_market"],
        "thermostat_model": RNG.choice(partner["models"]),
        "enrollment_date": format_enrollment_date(enrollment_dt, use_iso_date),
        "enrollment_status": RNG.choice(ENROLLMENT_STATUSES),
        "opt_out_date": opt_out_date,
        "signup_incentive_paid": signup_paid,
        "annual_incentive_paid": annual_paid,
    }


def build_base_rows(n: int) -> list[dict]:
    partner_names = list(PARTNERS.keys())
    zone_names = list(UTILITY_ZONES.keys())

    opted_out_mask = RNG.random(n) < 0.15
    strip_zero_mask = RNG.random(n) < 0.05
    underscore_mask = RNG.random(n) < 0.10
    iso_date_mask = RNG.random(n) < 0.60
    null_email_mask = RNG.random(n) < 0.02

    partner_choices = RNG.choice(partner_names, size=n)
    zone_choices = RNG.choice(zone_names, size=n)

    account_pool = [
        str(generate_utility_account_id(bool(RNG.random() < 0.05)))
        for _ in range(ACCOUNT_POOL_SIZE)
    ]

    rows: list[dict] = []
    for i in range(n):
        email = None if null_email_mask[i] else fake.unique.email()
        pooled_account = account_pool[i % ACCOUNT_POOL_SIZE] if i < HIGH_MATCH_ROWS else None
        rows.append(
            generate_row(
                partner_name=str(partner_choices[i]),
                customer_email=email,
                utility_zone=str(zone_choices[i]),
                opted_out=bool(opted_out_mask[i]),
                strip_account_zero=bool(strip_zero_mask[i]) if pooled_account is None else False,
                use_underscore_serial=bool(underscore_mask[i]),
                use_iso_date=bool(iso_date_mask[i]),
                utility_account_id=pooled_account,
            )
        )
    return rows


def add_duplicate_rows(rows: list[dict], duplicate_count: int) -> list[dict]:
    """Re-enrollment: same email, new device_serial."""
    if duplicate_count <= 0 or not rows:
        return rows

    eligible = [r for r in rows if r["customer_email"] is not None]
    if not eligible:
        return rows

    indices = RNG.choice(len(eligible), size=duplicate_count, replace=True)
    for idx in indices:
        source = eligible[int(idx)].copy()
        partner_name = source["partner_name"]
        partner = PARTNERS[partner_name]
        source["device_serial"] = generate_device_serial(
            partner["prefix"],
            bool(RNG.random() < 0.10),
        )
        source["enrollment_date"] = format_enrollment_date(
            random_enrollment_date(),
            bool(RNG.random() < 0.60),
        )
        rows.append(source)
    return rows


def trim_to_target(rows: list[dict], target: int) -> list[dict]:
    if len(rows) <= target:
        return rows
    return rows[:target]


def main() -> None:
    duplicate_count = int(round(TOTAL_ROWS * 0.03))
    base_count = TOTAL_ROWS - duplicate_count

    rows = build_base_rows(base_count)
    rows = add_duplicate_rows(rows, duplicate_count)
    rows = trim_to_target(rows, TOTAL_ROWS)

    df = pd.DataFrame(rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(
        OUTPUT_PATH,
        index=False,
        na_rep="",
    )

    print(f"Wrote {len(df):,} rows to {OUTPUT_PATH}")
    print(f"\nTotal rows: {len(df):,}")
    print("\nRows per partner:")
    for partner, count in df["partner_name"].value_counts().sort_index().items():
        print(f"  {partner}: {count:,}")
    print("\nRows per utility zone:")
    for zone, count in df["utility_zone"].value_counts().sort_index().items():
        print(f"  {zone}: {count:,}")


if __name__ == "__main__":
    main()
