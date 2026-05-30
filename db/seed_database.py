"""Seed the Voltus internal SQLite database with realistic 2024-2025 data."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "db" / "voltus_internal.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
ENROLLMENT_CSV = PROJECT_ROOT / "data" / "raw" / "partner_enrollment_portal.csv"

RNG = np.random.default_rng(42)
fake = Faker("en_US")
Faker.seed(42)

CUSTOMER_COUNT = 6500

PARTNERS = [
    (
        1,
        "Resideo Grid Services",
        "https://api.resideo.com/vpp/v1",
        "2022-01-15",
        0.15,
        "grid-services@resideo.com",
    ),
    (
        2,
        "Google Nest Energy",
        "https://nestenergy.googleapis.com/v1",
        "2022-06-01",
        0.18,
        "vpp-partners@google.com",
    ),
    (
        3,
        "ecobee Energy",
        "https://api.ecobee.com/energy/v2",
        "2023-03-10",
        0.12,
        "energy@ecobee.com",
    ),
    (
        4,
        "Octopus Energy US",
        "https://api.octopusenergy.us/dr/v1",
        "2024-01-08",
        0.20,
        "dr-partners@octopusenergy.us",
    ),
]

PROGRAMS = [
    (
        1,
        "ComEd CSRP Residential Thermostat",
        "PJM",
        "ComEd",
        "capacity_dr",
        8.50,
        "summer",
    ),
    (
        2,
        "PPL Act 129 Smart Thermostat DR",
        "PJM",
        "PPL",
        "economic_dr",
        6.25,
        "summer",
    ),
    (
        3,
        "PECO Energy Wise Emergency Response",
        "PJM",
        "PECO",
        "emergency_event",
        10.00,
        "summer",
    ),
    (
        4,
        "PSEG-LI Peak Savers Capacity",
        "NYISO",
        "PSEG-LI",
        "capacity_dr",
        12.00,
        "summer",
    ),
    (
        5,
        "Ameren Illinois Power Smart Pricing DR",
        "MISO",
        "AmerenIL",
        "capacity_dr",
        7.75,
        "summer",
    ),
    (
        6,
        "Voltus PJM Economic Load Response",
        "PJM",
        "ComEd",
        "economic_dr",
        5.50,
        "summer",
    ),
]

UTILITY_BY_STATE = {
    "ComEd": {"state": "IL", "iso": "PJM", "program_id": 1, "partner_ids": [1, 2, 3]},
    "AmerenIL": {"state": "IL", "iso": "MISO", "program_id": 5, "partner_ids": [1, 3, 4]},
    "PPL": {"state": "PA", "iso": "PJM", "program_id": 2, "partner_ids": [1, 2, 4]},
    "PECO": {"state": "PA", "iso": "PJM", "program_id": 3, "partner_ids": [2, 3, 4]},
    "PSEG-LI": {"state": "NY", "iso": "NYISO", "program_id": 4, "partner_ids": [2, 3, 4]},
}

ENROLLMENT_STATUSES = ["active", "pending", "inactive", "opted_out", "suspended"]

CONTRADICTORY_NOTES = [
    ("active", "Customer opted out on 2024-08-12 per phone call; awaiting portal sync."),
    ("active", "Status should be inactive - device offline since July."),
    ("inactive", "Re-enrolled 2024-09-01 after thermostat replacement."),
    ("inactive", "Confirmed active in partner portal export 2024-08-20."),
    ("opted_out", "Customer requested re-activation 2024-07-05; still enrolled."),
    ("pending", "Enrollment complete; status stuck in pending since 2024-05-01."),
    ("suspended", "Customer participating in last 3 events - verify suspension."),
    ("active", "Notes from partner: ENROLLED status, not active."),
]

DR_EVENTS = [
    (1, "2024-06-18", "14:00", "18:00", "PJM", 12.4, 10.8, "capacity_dr", 94.0),
    (2, "2024-06-28", "13:00", "17:00", "PJM", 8.6, 7.1, "economic_dr", 91.0),
    (4, "2024-07-09", "15:00", "19:00", "NYISO", 6.2, 5.4, "capacity_dr", 96.0),
    (1, "2024-07-17", "14:00", "18:00", "PJM", 14.1, 11.9, "capacity_dr", 98.0),
    (5, "2024-07-24", "13:00", "17:00", "MISO", 5.5, 4.7, "capacity_dr", 93.0),
    (3, "2024-08-06", "16:00", "20:00", "PJM", 9.8, 8.2, "emergency_event", 99.0),
    (6, "2024-08-14", "14:00", "18:00", "PJM", 7.3, 6.0, "economic_dr", 92.0),
    (4, "2024-09-03", "15:00", "19:00", "NYISO", 5.9, 5.1, "capacity_dr", 88.0),
]


def load_schema(conn: sqlite3.Connection) -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)


def generate_utility_account(strip_leading_zero: bool) -> str:
    if strip_leading_zero:
        # Originally 0-prefixed; stored without leading zero to mismatch CSV exports.
        trailing = RNG.integers(0, 10, size=9)
        return "".join(str(d) for d in trailing)
    digits = RNG.integers(0, 10, size=10)
    return "".join(str(d) for d in digits)


def random_created_at() -> str:
    start = datetime(2023, 1, 1)
    end = datetime(2025, 3, 1)
    offset = int(RNG.integers(0, (end - start).days + 1))
    return (start + timedelta(days=offset)).strftime("%Y-%m-%d %H:%M:%S")


def random_enrolled_date(use_timezone: bool) -> str:
    start = datetime(2024, 1, 1)
    end = datetime(2025, 3, 1)
    offset = int(RNG.integers(0, (end - start).days + 1))
    dt = start + timedelta(days=offset)
    if use_timezone:
        return dt.strftime("%Y-%m-%dT00:00:00-05:00")
    return dt.strftime("%Y-%m-%d")


def format_capacity_kw(as_string: bool) -> str | float:
    value = round(float(RNG.uniform(0.4, 2.5)), 1)
    if as_string:
        return f"{value} kW"
    return value


def load_shared_account_pool() -> list[str]:
    if not ENROLLMENT_CSV.exists():
        return []
    df = pd.read_csv(ENROLLMENT_CSV, dtype={"utility_account_id": str})
    accounts = df["utility_account_id"].dropna().astype(str).tolist()
    # Preserve deterministic pool order for DB ↔ portal joins.
    seen: set[str] = set()
    pool: list[str] = []
    for account in accounts:
        if account not in seen:
            seen.add(account)
            pool.append(account)
        if len(pool) >= CUSTOMER_COUNT:
            break
    return pool


def build_customers() -> list[tuple]:
    utilities = list(UTILITY_BY_STATE.keys())
    utility_choices = RNG.choice(utilities, size=CUSTOMER_COUNT)
    shared_accounts = load_shared_account_pool()

    strip_zero_mask = RNG.random(CUSTOMER_COUNT) < 0.05
    duplicate_count = int(round(CUSTOMER_COUNT * 0.02))
    unique_count = CUSTOMER_COUNT - duplicate_count

    customers: list[tuple] = []
    emails_for_duplication: list[str] = []

    for i in range(unique_count):
        utility = str(utility_choices[i])
        meta = UTILITY_BY_STATE[utility]
        email = fake.unique.email()
        emails_for_duplication.append(email)

        if shared_accounts and i < len(shared_accounts):
            account = shared_accounts[i]
        else:
            account = generate_utility_account(bool(strip_zero_mask[i]))

        customers.append(
            (
                str(uuid.uuid4()),
                fake.name(),
                email,
                fake.street_address(),
                fake.city(),
                meta["state"],
                fake.zipcode_in_state(meta["state"]),
                account,
                utility,
                random_created_at(),
            )
        )

    dup_indices = RNG.choice(unique_count, size=duplicate_count, replace=True)
    for idx in dup_indices:
        source = customers[int(idx)]
        customers.append(
            (
                str(uuid.uuid4()),
                source[1],
                source[2],
                fake.street_address(),
                source[4],
                source[5],
                fake.zipcode_in_state(source[5]),
                generate_utility_account(bool(RNG.random() < 0.05)),
                source[8],
                random_created_at(),
            )
        )

    return customers


def build_enrollments(customers: list[tuple]) -> list[tuple]:
    string_capacity_mask = RNG.random(len(customers)) < 0.03
    timezone_date_mask = RNG.random(len(customers)) < 0.10
    contradictory_mask = RNG.random(len(customers)) < 0.08

    enrollments: list[tuple] = []
    for i, customer in enumerate(customers):
        utility = customer[8]
        meta = UTILITY_BY_STATE[utility]
        program_id = meta["program_id"]
        partner_id = int(RNG.choice(meta["partner_ids"]))
        status = str(RNG.choice(ENROLLMENT_STATUSES))

        notes = None
        if contradictory_mask[i]:
            note_status, note_text = CONTRADICTORY_NOTES[
                int(RNG.integers(0, len(CONTRADICTORY_NOTES)))
            ]
            _ = note_status
            notes = note_text
        elif RNG.random() < 0.25:
            notes = RNG.choice(
                [
                    "Thermostat firmware updated.",
                    "Customer prefers SMS notifications.",
                    "Dual-fuel HVAC; confirm curtailment limits.",
                    "Partner sync lag reported in Q3.",
                    None,
                ]
            )

        enrollments.append(
            (
                customer[0],
                program_id,
                partner_id,
                random_enrolled_date(bool(timezone_date_mask[i])),
                status,
                format_capacity_kw(bool(string_capacity_mask[i])),
                notes,
            )
        )

    return enrollments


def seed(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """
        INSERT INTO partners (
            partner_id, partner_name, api_endpoint,
            contract_start_date, revenue_share_pct, contact_email
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        PARTNERS,
    )

    conn.executemany(
        """
        INSERT INTO programs (
            program_id, program_name, iso_market, utility_name,
            program_type, capacity_rate_per_kw, season
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        PROGRAMS,
    )

    customers = build_customers()
    conn.executemany(
        """
        INSERT INTO customers (
            voltus_customer_id, full_name, email, address, city, state, zip,
            utility_account_number, utility_name, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        customers,
    )

    enrollments = build_enrollments(customers)
    conn.executemany(
        """
        INSERT INTO enrollments (
            voltus_customer_id, program_id, partner_id,
            enrolled_date, status, capacity_kw, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        enrollments,
    )

    conn.executemany(
        """
        INSERT INTO dr_events (
            program_id, event_date, event_start_time, event_end_time,
            iso_market, mw_called, mw_delivered, event_type, temperature_f
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        DR_EVENTS,
    )


def print_row_counts(conn: sqlite3.Connection) -> None:
    tables = ["partners", "programs", "customers", "enrollments", "dr_events"]
    print(f"Database: {DB_PATH}\n")
    for table in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count:,}")


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        load_schema(conn)
        seed(conn)
        conn.commit()
        print_row_counts(conn)


if __name__ == "__main__":
    main()
