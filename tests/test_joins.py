"""Join integrity tests for processed VPP outputs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED = PROJECT_ROOT / "data" / "processed"


@pytest.fixture(scope="module")
def vpp_master() -> pd.DataFrame:
    path = PROCESSED / "vpp_master.parquet"
    assert path.exists(), "Run run_pipeline.py before tests."
    return pd.read_parquet(path)


@pytest.fixture(scope="module")
def cbl_performance() -> pd.DataFrame:
    path = PROCESSED / "cbl_performance.parquet"
    assert path.exists(), "Run run_pipeline.py before tests."
    return pd.read_parquet(path)


def test_vpp_master_no_duplicate_customer_event(vpp_master: pd.DataFrame) -> None:
    matched = vpp_master[vpp_master["voltus_customer_id"].notna() & vpp_master["event_id"].notna()]
    duplicates = matched.duplicated(subset=["voltus_customer_id", "event_id"], keep=False)
    assert not duplicates.any(), f"Found {duplicates.sum()} duplicate customer/event rows"


def test_utility_account_join_match_rate(vpp_master: pd.DataFrame) -> None:
    match_rate = (vpp_master["match_confidence"] != "unmatched").mean()
    assert match_rate > 0.85, f"Match rate {match_rate:.1%} is below 85%"


def test_cbl_values_present_for_sufficient_baseline(cbl_performance: pd.DataFrame) -> None:
    sufficient = cbl_performance[~cbl_performance["insufficient_baseline_days"]]
    assert not sufficient.empty
    assert sufficient["total_cbl_kwh"].notna().all()


def test_all_eight_events_in_cbl_output(cbl_performance: pd.DataFrame) -> None:
    events = sorted(cbl_performance["event_id"].dropna().unique())
    assert len(events) == 8, f"Expected 8 events, found {len(events)}: {events}"
