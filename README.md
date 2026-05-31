# Voltus Residential VPP Analytics

End-to-end analytics platform for a residential Virtual Power Plant (VPP) workflow . The type of system energy teams use to enroll smart thermostat customers, track demand response events, measure load reduction, validate interval data, and reconcile customer/partner settlements.

This is an independent synthetic demo project built to explore how residential VPP data from different sources can be linked into a trustworthy analytics view. It does **not** use or represent Voltus internal systems or data.

## Live Demo and Walkthrough

**Live Streamlit Demo:**
https://voltus-vpp-analytics-vtwblygoiug49bjozpcggg.streamlit.app

**4-Minute Video Walkthrough:**
https://drive.google.com/file/d/1iERrvCTatyPM6_m_nvmUmXwCOoM1j1Sx/view?usp=sharing

## Project Summary

Residential VPP data usually does not live in one clean system. It can come from partner enrollment portals, internal customer databases, device APIs, and 15-minute utility interval meter files. These sources are related, but they often have different identifiers, missing records, inconsistent formats, and data-quality issues.

This project shows how an analytics workflow can ingest, clean, link, validate and report on those sources. The final dashboard covers enrollment funnel analysis, partner and device performance, demand response event performance, interval data quality, and settlement reconciliation.

## Dashboard Preview

The Streamlit dashboard turns the cleaned and linked VPP data into an operational view for enrollment, partner performance, event performance, meter data quality, and settlement reconciliation.

### Enrollment Funnel

Tracks how customers move from lead capture to utility authorization, market registration, active enrollment, event participation, and retention.

<img width="1506" height="844" alt="image" src="https://github.com/user-attachments/assets/0bf04a85-d483-4c9a-ac15-14f5fc05d8e9" />


### Partner & Device Summary

Compares enrolled devices across partners and utility zones, helping identify which partners have the largest footprint and where growth is happening.

<img width="1215" height="671" alt="image" src="https://github.com/user-attachments/assets/cf917611-8b75-49ef-ab31-b136c08129e8" />


### Event Performance

Compares MW called versus MW delivered for each demand response event, showing whether the program delivered the expected load reduction.

<img width="1214" height="824" alt="image" src="https://github.com/user-attachments/assets/66b2b00c-26e9-4591-9868-5ece6a985d5c" />


### Settlement Reconciliation

Compares customer baseline load with actual usage during events, estimates incentive value, and flags negative reduction cases.

<img width="1210" height="848" alt="image" src="https://github.com/user-attachments/assets/0ce04d77-9f81-4873-a2fe-4a4c9fd917ea" />


## What Problem Does This Solve?

Utility-backed residential VPP programs pull data from several sources that do not always line up cleanly.

| Source                           | What it contains                                                   | Typical issues                                                           |
| -------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| Partner enrollment CSV files     | Customer signups, partner names, device serials, enrollment status | Mixed date formats, inconsistent status values, duplicate records        |
| Internal customer database       | Customer records, programs, partners, demand response events       | Leading-zero account IDs, duplicate emails, missing customer-event links |
| Thermostat/device API-style data | Device connectivity, telemetry, operational status                 | Missing devices, different device ID formats, offline devices            |
| Utility interval meter data      | 15-minute kWh usage reads before, during, and after events         | Missing intervals, estimated reads, negative values                      |
| EIA grid data                    | ISO-level demand context                                           | API limits, cache requirements, external data dependency                 |


## Key Business Questions Covered

| Dashboard Tab             | Business Question                                                            |
| ------------------------- | ---------------------------------------------------------------------------- |
| Enrollment Funnel         | How many customers move from signup to active participation?                 |
| Partner & Device Summary  | Which partners have the most enrolled devices and which are growing fastest? |
| Event Performance         | How much MW was called versus delivered during demand response events?       |
| Interval Data Quality     | Are 15-minute meter reads complete, actual, estimated, or missing?           |
| Settlement Reconciliation | What did customers actually reduce and what incentive value is owed?         |


## Pipeline Stages

| Step | Script                                        | Purpose                                                                     |
| ---- | --------------------------------------------- | --------------------------------------------------------------------------- |
| 1    | `synthetic/generate_enrollment_csv.py`        | Generates 8,000 enrollment rows with intentional data-quality issues        |
| 2    | `db/seed_database.py`                         | Seeds SQLite CRM database with customers, partners, programs, and DR events |
| 3    | `synthetic/generate_interval_data.py`         | Generates 15-minute interval meter data for demand response events          |
| 4    | `synthetic/mock_thermostat_api.py`            | Runs a mock Flask API for thermostat/device data                            |
| 5    | `ingestion/05_ingest_eia_api.py`              | Ingests or loads cached EIA grid demand context                             |
| 6    | `ingestion/01_clean_all_sources.py`           | Cleans raw sources and writes standardized parquet files                    |
| 7    | `transform/02_link_entities.py`               | Links customers, devices, partners, events, and meter records               |
| 8    | `transform/03_compute_cbl_and_performance.py` | Calculates customer baseline load and event performance                     |

Run the full pipeline with:

```bash
python run_pipeline.py
```

Target runtime: under 60 seconds on a typical laptop.

## Quick Start

### Prerequisites

* Python 3.11+
* Git

### 1. Clone the repository

```bash
git clone https://github.com/tarashbudhrani/voltus-vpp-analytics.git
cd voltus-vpp-analytics
```


### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set environment variables

```bash
cp .env.example .env
```

An EIA API key is optional for the first run because cached grid data is included in `data/eia_cache/`.

If you want to pull fresh EIA data, add your key to `.env`:

```bash
EIA_API_KEY=your_key_here
```

### 4. Run the pipeline

```bash
python run_pipeline.py
```

### 5. Launch the dashboard locally

```bash
streamlit run dashboard/streamlit_app.py
```

## Dashboard Filters

The dashboard includes sidebar filters so users can narrow the analysis by:

* ISO market
* Utility zone
* Partner
* Enrollment date range

The ISO market filter dynamically limits the available utility zones. Filters persist across dashboard tabs using Streamlit session state.


## Project Structure

```text
voltus-vpp-analytics/
├── run_pipeline.py
├── dashboard/
│   └── streamlit_app.py
├── synthetic/
│   ├── generate_enrollment_csv.py
│   ├── generate_interval_data.py
│   └── mock_thermostat_api.py
├── db/
│   ├── schema.sql
│   └── seed_database.py
├── ingestion/
│   ├── 01_clean_all_sources.py
│   └── 05_ingest_eia_api.py
├── transform/
│   ├── 02_link_entities.py
│   └── 03_compute_cbl_and_performance.py
├── sql/
├── tests/
├── assets/
│   ├── enrollment_funnel.png
│   ├── partner_device_summary.png
│   ├── event_performance.png
│   └── settlement_reconciliation.png
├── data/
│   ├── eia_cache/
│   ├── raw/
│   └── processed/
└── requirements.txt
```

## Data Quality and Validation Focus

A major focus of this project is not just building charts, but making sure the data behind the dashboard is trustworthy.

The pipeline includes checks for:

* Missing customer IDs
* Duplicate records
* Mismatched device IDs
* Missing meter intervals
* Negative or invalid kWh values
* Estimated versus actual meter reads
* Join completeness across enrollment, customer, device, event, and interval data
* Metrics tying out across source tables and dashboard outputs

This matters because if the joins are wrong, then the enrollment funnel, event performance metrics, and settlement calculations will also be wrong.

## Tech Stack

* Python
* pandas
* pyarrow
* SQLite
* Flask
* Streamlit
* Plotly
* pytest

## Why I Built This

I built this project after applying for the Residential Data Analyst Intern role because I was interested in residential energy markets and wanted to better understand how residential VPP data workflows can be linked into a trusted analytics layer.

The project was designed around the type of multi-source analytics problem where data comes from partner portals, internal databases, device APIs, and utility meter files, and the analyst needs to identify the keys, validate the joins, find gaps, and create useful operational reporting.



## License

MIT
