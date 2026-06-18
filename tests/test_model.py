"""Tests for the ML model input validation and training utilities."""

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.models.train import evaluate, time_series_cv, FEATURE_COLS


# ── evaluate ────────────────────────────────────────────────────────────────

def _dummy_model():
    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=200)),
    ])
    X = np.random.default_rng(0).normal(size=(200, 3))
    y = (X[:, 0] + np.random.default_rng(1).normal(size=200) > 0).astype(int)
    pipe.fit(X, y)
    return pipe, X, y


def test_evaluate_returns_all_keys():
    model, X, y = _dummy_model()
    metrics = evaluate(model, X, y)
    assert set(metrics.keys()) == {"accuracy", "roc_auc", "precision", "recall", "f1"}


def test_evaluate_accuracy_in_range():
    model, X, y = _dummy_model()
    metrics = evaluate(model, X, y)
    assert 0.0 <= metrics["accuracy"] <= 1.0


def test_evaluate_auc_in_range():
    model, X, y = _dummy_model()
    metrics = evaluate(model, X, y)
    assert 0.0 <= metrics["roc_auc"] <= 1.0


# ── time_series_cv ──────────────────────────────────────────────────────────

def _make_feature_df(n=300):
    rng = np.random.default_rng(42)
    X = pd.DataFrame(rng.normal(size=(n, 4)), columns=["f1", "f2", "f3", "f4"])
    y = pd.Series((X["f1"] + rng.normal(size=n) > 0).astype(int))
    return X, y


def test_time_series_cv_returns_mean_metrics():
    pipe = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(max_iter=200))])
    X, y = _make_feature_df()
    result = time_series_cv(pipe, X, y, n_splits=3)
    assert "cv_mean" in result
    assert "roc_auc" in result["cv_mean"]
    assert 0.0 <= result["cv_mean"]["roc_auc"] <= 1.0


def test_time_series_cv_no_future_leak():
    """Verify that test set indices are always strictly after train set indices."""
    from sklearn.model_selection import TimeSeriesSplit
    X, y = _make_feature_df(300)
    tscv = TimeSeriesSplit(n_splits=5)
    for train_idx, test_idx in tscv.split(X):
        assert max(train_idx) < min(test_idx), "Train set bleeds into test set"


# ── feature validation ───────────────────────────────────────────────────────

def test_feature_cols_defined():
    assert len(FEATURE_COLS) >= 6, "Expected at least 6 features"


def test_feature_cols_no_duplicates():
    assert len(FEATURE_COLS) == len(set(FEATURE_COLS))


# ── API input validation ─────────────────────────────────────────────────────

def test_api_pead_explorer_invalid_ticker():
    from fastapi.testclient import TestClient
    from src.api.main import app
    client = TestClient(app)
    resp = client.get("/api/pead-explorer?ticker=ZZZZNOTREAL")
    assert resp.status_code == 404


def test_api_tickers_returns_list():
    from fastapi.testclient import TestClient
    from src.api.main import app
    client = TestClient(app)
    resp = client.get("/api/tickers")
    assert resp.status_code == 200
    assert "tickers" in resp.json()
    assert isinstance(resp.json()["tickers"], list)


def test_api_sectors_returns_list():
    from fastapi.testclient import TestClient
    from src.api.main import app
    client = TestClient(app)
    resp = client.get("/api/sectors")
    assert resp.status_code == 200
    assert "sectors" in resp.json()


def test_api_signal_dashboard_returns_signals():
    from fastapi.testclient import TestClient
    from src.api.main import app
    client = TestClient(app)
    resp = client.get("/api/signal-dashboard?n=10")
    assert resp.status_code == 200
    body = resp.json()
    assert "signals" in body
    assert len(body["signals"]) <= 10


def test_api_methodology_returns_metrics():
    from fastapi.testclient import TestClient
    from src.api.main import app
    client = TestClient(app)
    resp = client.get("/api/methodology")
    assert resp.status_code == 200
    body = resp.json()
    assert "model_name" in body
    assert "metrics" in body
