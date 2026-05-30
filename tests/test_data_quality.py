"""Data quality tests for cleaned pipeline outputs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED = PROJECT_ROOT / "data" / "processed"

ALLOWED_STATUSES = {"active", "inactive", "opted_out"}


@pytest.fixture(scope="module")
def enrollment_clean() -> pd.DataFrame:
    path = PROCESSED / "enrollment_clean.parquet"
    assert path.exists(), "Run run_pipeline.py before tests."
    return pd.read_parquet(path)


@pytest.fixture(scope="module")
def interval_clean() -> pd.DataFrame:
    path = PROCESSED / "interval_clean.parquet"
    assert path.exists(), "Run run_pipeline.py before tests."
    return pd.read_parquet(path)


def test_enrollment_dates_are_datetime(enrollment_clean: pd.DataFrame) -> None:
    assert pd.api.types.is_datetime64_any_dtype(enrollment_clean["enrollment_date"])


def test_enrollment_status_allowed_values(enrollment_clean: pd.DataFrame) -> None:
    values = set(enrollment_clean["enrollment_status"].dropna().unique())
    assert values.issubset(ALLOWED_STATUSES), f"Unexpected statuses: {values - ALLOWED_STATUSES}"


def test_interval_usage_present_for_valid_rows(interval_clean: pd.DataFrame) -> None:
    valid = interval_clean[~interval_clean["is_error"].fillna(False)]
    assert valid["usage_kwh"].notna().all()


def test_device_serials_use_dash_format(enrollment_clean: pd.DataFrame) -> None:
    serials = enrollment_clean["device_serial"].astype(str)
    assert not serials.str.contains("_").any(), "Found underscore device serials after cleaning"
