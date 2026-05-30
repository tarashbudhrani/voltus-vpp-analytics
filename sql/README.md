# SQL Analytics Queries

These queries support Voltus residential VPP operations reporting. They are written in **standard SQLite-compatible SQL** and are designed to run in [Redash](https://redash.io/) connected to `db/voltus_internal.db`, or adapted to PostgreSQL in production.

## Prerequisites

### Core database

Most queries use tables from `voltus_internal.db`:

| Table | Description |
|-------|-------------|
| `customers` | Voltus CRM customer records |
| `enrollments` | Program enrollments linked to customers and partners |
| `programs` | DR program definitions and capacity rates |
| `partners` | OEM / aggregator partner contracts |
| `dr_events` | Dispatch events with MW called vs delivered |

Seed the database before running queries:

```bash
python db/seed_database.py
```

### Staging tables (cleaned pipeline output)

Queries **02**, **04**, and **05** also require staging tables loaded from the ingestion pipeline (`ingestion/01_clean_all_sources.py`). Import the cleaned parquet files into the same SQLite database (or attach them as a separate schema in Redash):

```bash
python ingestion/01_clean_all_sources.py
```

Then load staging tables — example using Python:

```python
import pandas as pd
import sqlite3

conn = sqlite3.connect("db/voltus_internal.db")
pd.read_parquet("data/processed/enrollment_clean.parquet").to_sql(
    "enrollment_clean", conn, if_exists="replace", index=False
)
pd.read_parquet("data/processed/interval_clean.parquet").to_sql(
    "interval_clean", conn, if_exists="replace", index=False
)
conn.close()
```

## Query catalog

| File | Business question | Primary sources |
|------|-------------------|-----------------|
| `01_enrollment_funnel.sql` | How many customers are at each enrollment funnel stage? | `customers`, `enrollments`, `dr_events` |
| `02_partner_registration_summary.sql` | Devices enrolled per partner/zone/week and WoW growth? | `enrollment_clean` |
| `03_event_performance.sql` | MW called vs delivered and customer response rate per event? | `dr_events`, `enrollments`, `programs` |
| `04_data_quality_monitor.sql` | Actual vs estimated vs missing interval reads per event? | `interval_clean` |
| `05_settlement_reconciliation.sql` | Baseline vs event usage, reduction kW, and revenue per customer? | `interval_clean`, `customers`, `enrollments`, `programs`, `dr_events` |

## Running in Redash

1. Add a SQLite data source pointing to `voltus_internal.db`.
2. Paste the contents of any `.sql` file into a new query.
3. For staging-dependent queries, ensure `enrollment_clean` and `interval_clean` are loaded first.

## Production (PostgreSQL) notes

When moving to production:

- Replace `strftime()` / `julianday()` with PostgreSQL `date_trunc()` / `EXTRACT(EPOCH FROM ...)`.
- Replace `ltrim(..., '0')` account matching with normalized account ID columns maintained in ETL.
- Map staging tables to warehouse schemas (e.g. `staging.enrollment_clean`, `staging.interval_reads`).
- `01_enrollment_funnel.sql` and `03_event_performance.sql` run entirely against operational tables and translate directly.

## Join design philosophy

Each SQL file includes inline comments explaining **what each JOIN does and why**. Joins are intentionally explicit (rather than hidden in views) so analysts can audit match logic — especially for known data quality issues like utility account leading zeros and partner portal vs internal ID mismatches.
