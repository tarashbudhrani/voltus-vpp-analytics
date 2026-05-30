"""Ingest EIA grid demand data (cache-first, optional live API)."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "eia_cache"
CACHE_PATH = CACHE_DIR / "eia_grid_demand.csv"
PROCESSED_PATH = PROJECT_ROOT / "data" / "processed" / "eia_demand_clean.parquet"

EIA_SERIES = {
    "PJM": "EBA.PJM-ALL.D.H",
    "NYISO": "EBA.NYIS-ALL.D.H",
    "MISO": "EBA.MISO-ALL.D.H",
}


def load_cache() -> pd.DataFrame | None:
    if CACHE_PATH.exists():
        return pd.read_csv(CACHE_PATH, parse_dates=["period"])
    return None


def fetch_live(api_key: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for iso_market, series_id in EIA_SERIES.items():
        url = (
            "https://api.eia.gov/v2/electricity/rto/daily-region-data/data/"
            f"?api_key={api_key}&frequency=daily&data[0]=value"
            f"&facets[type][]=D&facets[respondent][]={series_id.split('.')[1].split('-')[0]}"
        )
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("response", {}).get("data", [])
            if not rows:
                continue
            chunk = pd.DataFrame(rows)
            chunk = chunk.rename(columns={"period": "period", "value": "demand_mwh"})
            chunk["iso_market"] = iso_market
            chunk["region"] = iso_market
            chunk["avg_temperature_f"] = pd.NA
            frames.append(chunk[["period", "iso_market", "region", "demand_mwh", "avg_temperature_f"]])
        except requests.RequestException:
            continue

    if not frames:
        raise RuntimeError("Live EIA API request failed for all ISO markets.")
    return pd.concat(frames, ignore_index=True)


def write_outputs(df: pd.DataFrame) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CACHE_PATH, index=False)
    df.to_parquet(PROCESSED_PATH, index=False)


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("EIA_API_KEY", "")

    cached = load_cache()
    if cached is not None:
        print(f"Using cached EIA data -> {CACHE_PATH} ({len(cached):,} rows)")
        write_outputs(cached)
        return

    if not api_key or api_key == "your_key_here":
        raise FileNotFoundError(
            f"No EIA cache at {CACHE_PATH} and no valid EIA_API_KEY configured."
        )

    print("Cache missing — fetching EIA grid demand from API...")
    df = fetch_live(api_key)
    write_outputs(df)
    print(f"Saved EIA cache ({len(df):,} rows) -> {CACHE_PATH}")


if __name__ == "__main__":
    main()
