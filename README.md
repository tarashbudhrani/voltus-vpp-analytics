# Voltus Residential VPP Analytics

End-to-end analytics platform for a **residential Virtual Power Plant (VPP)** — the kind of system energy companies use to enroll smart thermostat customers, dispatch demand-response (DR) events, measure load reduction, and reconcile partner settlements.

This repository is a **complete demo pipeline**: synthetic multi-source data, realistic data-quality problems, batch ETL, SQL analytics, automated tests, and a Streamlit operations dashboard.

---

## What problem does this solve?

Utility-backed VPP programs pull data from many places that do not line up cleanly:

| Source | What it contains | Typical issues |
|--------|------------------|----------------|
| Partner enrollment portal | Customer sign-ups, device serials | Mixed date formats, inconsistent status values |
| Internal CRM database | Customers, programs, DR events | Leading-zero account IDs, duplicate emails |
| Thermostat partner API | Device telemetry, connectivity | Missing devices, underscore vs dash IDs |
| Utility interval meters | 15-minute kWh reads | Gaps, estimated reads, negative values |
| EIA grid data | ISO-level demand context | API rate limits, caching needs |

This project shows how an analytics team **ingests, cleans, joins, and reports** on that mess — producing enrollment funnel metrics, event performance (MW called vs delivered), interval data quality scores, and settlement views.

**Important:** Data is **batch, not streaming**. The pipeline writes static parquet files; the dashboard reads those snapshots. Re-run the pipeline to refresh numbers.

---

## Architecture

```mermaid
flowchart LR
    subgraph sources [Data sources]
        CSV[Partner CSV]
        DB[(SQLite CRM)]
        API[Mock thermostat API]
        INT[Interval CSVs]
        EIA[EIA grid cache]
    end

    subgraph pipeline [Batch pipeline]
        GEN[synthetic/]
        ING[ingestion/]
        TX[transform/]
    end

    subgraph outputs [Outputs]
        PQ[data/processed/*.parquet]
        SQL[sql/]
        UI[dashboard/]
    end

    GEN --> CSV
    GEN --> DB
    GEN --> API
    GEN --> INT
    CSV --> ING
    DB --> ING
    API --> ING
    INT --> ING
    EIA --> ING
    ING --> TX
    TX --> PQ
    PQ --> UI
    PQ --> SQL
```

### Pipeline stages

| Step | Script | Purpose |
|------|--------|---------|
| 1 | `synthetic/generate_enrollment_csv.py` | 8,000 enrollment rows with intentional quality issues |
| 2 | `db/seed_database.py` | SQLite CRM: 6,500 customers, 8 DR events |
| 3 | `synthetic/generate_interval_data.py` | Interval meter files per event |
| 4 | `synthetic/mock_thermostat_api.py` | Flask API on port 5001 (7,200 devices) |
| 5 | `ingestion/05_ingest_eia_api.py` | Grid demand (cache-first) |
| 6 | `ingestion/01_clean_all_sources.py` | Clean all sources → parquet |
| 7 | `transform/02_link_entities.py` | Join sources → `vpp_master.parquet` |
| 8 | `transform/03_compute_cbl_and_performance.py` | HighXofY CBL → `cbl_performance.parquet` |

Run everything with one command:

```bash
python run_pipeline.py
```

Target runtime: **under 60 seconds** on a typical laptop.

---

## Quick start (first time)

### Prerequisites

- **Python 3.11+** (3.12 or 3.13 recommended)
- **git**

### 1. Clone and enter the project

```bash
git clone https://github.com/YOUR_USERNAME/voltus-vpp-analytics.git
cd voltus-vpp-analytics
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Environment variables (optional)

```bash
cp .env.example .env
```

An EIA API key is **not required** for first run — cached grid data ships in `data/eia_cache/`. Set `EIA_API_KEY` only if you want to pull fresh EIA data.

Get a free key: [https://www.eia.gov/opendata/register.php](https://www.eia.gov/opendata/register.php)

### 5. Build the dataset

```bash
python run_pipeline.py
```

You should see eight steps complete and a message like:

```text
Pipeline complete in ~45 seconds.
Run: streamlit run dashboard/streamlit_app.py
```

This creates:

- `data/processed/*.parquet` — cleaned, joined analytics tables
- `db/voltus_internal.db` — operational SQLite database

### 6. Launch the dashboard

```bash
streamlit run dashboard/streamlit_app.py
```

Open the URL shown in the terminal (usually **http://localhost:8501**).

### 7. Run tests (optional)

```bash
pytest tests/ -v
```

Tests validate join integrity and data quality rules. Run them **after** the pipeline.

---

## Dashboard

The Streamlit app is the primary way to explore results. Five tabs mirror the business questions operations teams ask:

| Tab | Question |
|-----|----------|
| **Enrollment Funnel** | How many customers move from signup → active participation? |
| **Partner & Device Summary** | Which OEM partners are growing? Are devices online? |
| **Event Performance** | MW called vs delivered per DR dispatch |
| **Interval Data Quality** | Actual vs estimated vs missing meter reads |
| **Settlement Reconciliation** | CBL vs actual load, incentives owed |

### Sidebar filters

- **ISO market** → dynamically limits **utility zone** options (PJM / MISO / NYISO mapping)
- **Partner**, **enrollment date range**
- Filters persist across tabs via session state

### Refreshing data

The dashboard does **not** update automatically. After changing data or re-running the pipeline:

1. Run `python run_pipeline.py`
2. Refresh the browser (press **R** in Streamlit, or restart the app)

---

## Deploy on Streamlit Community Cloud

1. Push this repo to GitHub (see below).
2. Go to [share.streamlit.io](https://share.streamlit.io) and connect the repo.
3. Set **Main file path**: `dashboard/streamlit_app.py`
4. Add `EIA_API_KEY` in Secrets only if you need live EIA pulls.

**Note:** Streamlit Cloud cannot run `run_pipeline.py` on every page load. Either:

- Commit pre-built `data/processed/` parquet files (remove those paths from `.gitignore` before pushing), **or**
- Add a CI step that runs the pipeline and commits artifacts.

For a portfolio demo, committing processed outputs (~few MB) is the simplest path.

---

## Project structure

```text
voltus-vpp-analytics/
├── run_pipeline.py              # One-command end-to-end runner
├── dashboard/
│   └── streamlit_app.py         # Operations dashboard
├── synthetic/                   # Data generators + mock API
├── db/
│   ├── schema.sql               # CRM table definitions
│   └── seed_database.py         # Populate SQLite
├── ingestion/                   # Clean raw sources
├── transform/                   # Entity linking + CBL performance
├── sql/                         # Redash-ready analytics queries
├── tests/                       # pytest data quality & join tests
├── data/
│   ├── eia_cache/               # Shipped EIA cache (no API key needed)
│   ├── raw/                     # Generated CSVs (gitignored)
│   └── processed/               # Parquet outputs (gitignored)
└── requirements.txt
```

---

## Key outputs

| File | Description |
|------|-------------|
| `enrollment_clean.parquet` | Standardized partner portal enrollments |
| `vpp_master.parquet` | Customer × event grain master table |
| `cbl_performance.parquet` | Baseline load + event performance per customer |
| `interval_clean.parquet` | Cleaned 15-minute meter intervals |
| `voltus_internal.db` | CRM: customers, programs, partners, DR events |

---

## SQL analytics

Production-style SQL lives in `sql/` for Redash or any SQLite client. See [`sql/README.md`](sql/README.md) for table prerequisites and query catalog.

---

## Push to GitHub

From the project root:

```bash
git init
git add .
git commit -m "Initial commit: Voltus residential VPP analytics pipeline"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/voltus-vpp-analytics.git
git push -u origin main
```

`.gitignore` excludes the virtual environment, secrets (`.env`), and generated `data/raw/`, `data/processed/`, and the SQLite DB. Anyone cloning the repo runs `python run_pipeline.py` once to regenerate them.

To ship a **ready-to-view dashboard** on Streamlit Cloud without requiring visitors to run the pipeline, temporarily allow processed data in git:

```bash
# Edit .gitignore — comment out data/processed/ — then:
python run_pipeline.py
git add data/processed/
git commit -m "Add processed dashboard artifacts"
git push
```

---

## Tech stack

Python · pandas · pyarrow · SQLite · Flask (mock API) · Streamlit · Plotly · pytest

---

## License

MIT (or update this section for your preferred license.)
