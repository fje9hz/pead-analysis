"""Tests for the data pipeline logic."""

import numpy as np
import pandas as pd
import pytest

from src.data.pipeline import (
    _sic_to_sector,
    compute_surprise,
    QUINTILE_LABELS,
)


# ── _sic_to_sector ──────────────────────────────────────────────────────────

def test_sic_to_sector_finance():
    assert _sic_to_sector(6020) == "Finance"

def test_sic_to_sector_manufacturing():
    assert _sic_to_sector(2500) == "Manufacturing"

def test_sic_to_sector_services():
    assert _sic_to_sector(7372) == "Services"  # SIC 7372 is 7000-7999 → Services

def test_sic_to_sector_null():
    assert _sic_to_sector(np.nan) == "Unknown"


# ── compute_surprise ────────────────────────────────────────────────────────

def _make_actuals():
    return pd.DataFrame({
        "ticker": ["AAPL", "AAPL", "MSFT"],
        "cusip": ["037833100", "037833100", "594918104"],
        "anndats": pd.to_datetime(["2020-01-30", "2020-07-30", "2020-01-29"]),
        "actual_eps": [4.99, 2.58, 1.51],
        "pdicity": ["ANN", "ANN", "ANN"],
        "curr_act": ["USD", "USD", "USD"],
    })


def _make_consensus():
    return pd.DataFrame({
        "ticker": ["AAPL", "AAPL", "AAPL", "MSFT"],
        "cusip": ["037833100"] * 3 + ["594918104"],
        "statpers": pd.to_datetime(["2020-01-01", "2020-01-20", "2020-07-01", "2020-01-01"]),
        "fpedats": pd.to_datetime(["2020-03-31"] * 3 + ["2020-03-31"]),
        "fpi": ["1"] * 4,
        "medest": [4.50, 4.55, 2.40, 1.40],
        "meanest": [4.48, 4.53, 2.38, 1.39],
        "stdev": [0.10, 0.09, 0.12, 0.05],
        "numest": [30, 32, 28, 25],
        "highest": [4.70, 4.75, 2.55, 1.60],
        "lowest": [4.20, 4.25, 2.20, 1.20],
    })


def test_compute_surprise_positive():
    result = compute_surprise(_make_actuals(), _make_consensus())
    aapl = result[result["ticker"] == "AAPL"]
    assert len(aapl) >= 1
    # AAPL beat: 4.99 vs ~4.55 -> positive surprise
    assert aapl.iloc[0]["surprise"] > 0


def test_compute_surprise_beat_column():
    result = compute_surprise(_make_actuals(), _make_consensus())
    assert "beat" in result.columns
    assert set(result["beat"].unique()).issubset({0, 1})


def test_compute_surprise_quintile_labels():
    result = compute_surprise(_make_actuals(), _make_consensus())
    assert "surprise_quintile" in result.columns
    valid = set(QUINTILE_LABELS)
    for q in result["surprise_quintile"].dropna():
        assert q in valid


def test_compute_surprise_clips_extremes():
    actuals = _make_actuals()
    consensus = _make_consensus()
    # Set one estimate to tiny value to test edge case
    consensus.loc[0, "medest"] = 0.001
    result = compute_surprise(actuals, consensus)
    assert result["surprise"].between(-2.0, 2.0).all()


def test_compute_surprise_drops_missing_estimate():
    actuals = _make_actuals()
    consensus = _make_consensus()
    consensus["medest"] = np.nan
    result = compute_surprise(actuals, consensus)
    assert len(result) == 0


def test_compute_surprise_requires_pre_announcement_estimate():
    """Estimates dated after the announcement should not be matched."""
    actuals = _make_actuals()
    consensus = _make_consensus()
    # Push all estimate dates well past all announcement dates
    consensus["statpers"] = pd.to_datetime("2025-06-01")
    result = compute_surprise(actuals, consensus)
    assert len(result) == 0
