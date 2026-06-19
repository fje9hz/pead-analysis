"""
FastAPI backend for the PEAD Analysis App.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

log = logging.getLogger("pead_api")

PROC_DIR = Path("data/processed")
AGG_DIR = PROC_DIR / "aggregates"
STATIC_DIR = Path("static")

app = FastAPI(
    title="PEAD Analysis API",
    description="Post-Earnings Announcement Drift research platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Data cache (loaded once at startup)
# ---------------------------------------------------------------------------

_cache: dict = {}
_refresh_lock = Lock()
_refresh_status = {
    "state": "idle",
    "started_at": None,
    "finished_at": None,
    "refresh_raw": False,
    "result": None,
    "error": None,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_refresh_token(token: Optional[str]):
    expected = os.getenv("PEAD_REFRESH_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Data refresh is disabled. Set PEAD_REFRESH_TOKEN to enable it.",
        )
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


def _run_refresh_job(refresh_raw: bool):
    global _cache
    try:
        from src.data import refresh

        with _refresh_lock:
            _refresh_status.update({
                "state": "running",
                "started_at": _utc_now(),
                "finished_at": None,
                "refresh_raw": refresh_raw,
                "result": None,
                "error": None,
            })

        result = refresh.run(refresh_raw=refresh_raw)

        with _refresh_lock:
            _cache = {}
            _load_data()
            _refresh_status.update({
                "state": "succeeded",
                "finished_at": _utc_now(),
                "result": result,
                "error": None,
            })
    except Exception as exc:
        log.exception("WRDS refresh failed")
        with _refresh_lock:
            _refresh_status.update({
                "state": "failed",
                "finished_at": _utc_now(),
                "result": None,
                "error": str(exc),
            })


def _load_aggregates() -> bool:
    """Load pre-computed WRDS aggregate files if they exist. Returns True if loaded."""
    overall_path = AGG_DIR / "overall.json"
    if not overall_path.exists():
        return False

    def _j(name):
        p = AGG_DIR / name
        return json.load(open(p)) if p.exists() else None

    _cache["agg_quintile_car"] = _j("quintile_car.json")
    _cache["agg_sector"]       = _j("sector_summary.json")
    _cache["agg_tickers"]      = _j("ticker_summary.json")
    _cache["agg_annual"]       = _j("annual_summary.json")
    _cache["agg_overall"]      = _j("overall.json")

    metrics_path = AGG_DIR / "model_metrics.json"
    if metrics_path.exists():
        _cache["metrics"] = json.load(open(metrics_path))

    fi_path = AGG_DIR / "feature_importance.csv"
    if fi_path.exists():
        import pandas as pd
        _cache["feat_imp"] = pd.read_csv(fi_path).to_dict(orient="records")

    # Build ticker list and sector list from aggregates
    if _cache["agg_tickers"]:
        _cache["tickers"] = sorted(t["ticker"] for t in _cache["agg_tickers"])
    if _cache["agg_sector"]:
        _cache["sectors"] = sorted(s["sector"] for s in _cache["agg_sector"] if s["sector"])

    _cache["is_real_data"] = True
    log.info("Loaded WRDS aggregate data from data/processed/aggregates/")
    return True


def _load_data():
    global _cache
    if _cache:
        return

    # Try real WRDS aggregates first
    if _load_aggregates():
        # Also try to load full features for the explorer (optional)
        features_path = PROC_DIR / "features.csv"
        if features_path.exists():
            df = pd.read_csv(features_path, low_memory=False)
            df["anndats"] = pd.to_datetime(df["anndats"])
            df["ann_year"] = df["anndats"].dt.year
            for col in ["surprise", "car_m1_p1", "car_0_p30", "car_0_p60"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            _cache["df"] = df
        return

    # Fall back to demo data
    _cache["is_real_data"] = False
    features_path = PROC_DIR / "features.csv"
    metrics_path = PROC_DIR / "model_metrics.json"
    feat_imp_path = PROC_DIR / "feature_importance.csv"

    if features_path.exists():
        df = pd.read_csv(features_path, low_memory=False)
        df["anndats"] = pd.to_datetime(df["anndats"])
        df["ann_year"] = df["anndats"].dt.year
        df["surprise"] = pd.to_numeric(df["surprise"], errors="coerce")
        for col in ["car_m1_p1", "car_0_p30", "car_0_p60"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        _cache["df"] = df
    else:
        # Load demo data if processed data doesn't exist yet
        _cache["df"] = _generate_demo_data()

    if metrics_path.exists():
        with open(metrics_path) as f:
            _cache["metrics"] = json.load(f)
    else:
        _cache["metrics"] = _demo_metrics()

    if feat_imp_path.exists():
        _cache["feat_imp"] = pd.read_csv(feat_imp_path).to_dict(orient="records")
    else:
        _cache["feat_imp"] = _demo_feat_importance()

    _cache["tickers"] = sorted(_cache["df"]["ticker"].dropna().unique().tolist())
    _cache["sectors"] = sorted(_cache["df"]["sector"].dropna().unique().tolist()) if "sector" in _cache["df"].columns else []


def _generate_demo_data() -> pd.DataFrame:
    """Synthetic demo data so the app runs without WRDS credentials."""
    np.random.seed(42)
    tickers = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "JPM", "JNJ",
        "V", "PG", "HD", "MA", "BAC", "XOM", "DIS", "NFLX", "TSLA",
        "ADBE", "CRM", "INTC", "PFE", "KO", "PEP", "WMT", "CVX",
    ]
    sectors = {
        "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
        "AMZN": "Consumer Discretionary", "META": "Technology", "NVDA": "Technology",
        "JPM": "Finance", "JNJ": "Healthcare", "V": "Finance", "PG": "Consumer Staples",
        "HD": "Consumer Discretionary", "MA": "Finance", "BAC": "Finance",
        "XOM": "Energy", "DIS": "Entertainment", "NFLX": "Entertainment",
        "TSLA": "Consumer Discretionary", "ADBE": "Technology", "CRM": "Technology",
        "INTC": "Technology", "PFE": "Healthcare", "KO": "Consumer Staples",
        "PEP": "Consumer Staples", "WMT": "Consumer Staples", "CVX": "Energy",
    }
    records = []
    for ticker in tickers:
        for year in range(2010, 2024):
            for quarter in range(4):
                month = [3, 6, 9, 12][quarter]
                ann_date = pd.Timestamp(year=year, month=month, day=15) + pd.Timedelta(days=np.random.randint(-5, 5))
                surprise = np.random.normal(0.04, 0.15)
                surprise = np.clip(surprise, -1.0, 1.0)
                mkt_drift = surprise * 0.3
                car_0_30 = mkt_drift + np.random.normal(0, 0.04)
                car_0_60 = mkt_drift * 1.5 + np.random.normal(0, 0.06)
                car_m1_p1 = surprise * 0.15 + np.random.normal(0, 0.03)

                quintile_val = surprise
                if quintile_val <= np.percentile([-0.3, -0.1, 0.0, 0.1, 0.3], 20):
                    quintile = "Large Miss"
                elif quintile_val <= np.percentile([-0.3, -0.1, 0.0, 0.1, 0.3], 40):
                    quintile = "Miss"
                elif quintile_val <= np.percentile([-0.3, -0.1, 0.0, 0.1, 0.3], 60):
                    quintile = "Inline"
                elif quintile_val <= np.percentile([-0.3, -0.1, 0.0, 0.1, 0.3], 80):
                    quintile = "Beat"
                else:
                    quintile = "Large Beat"

                records.append({
                    "ticker": ticker,
                    "anndats": ann_date,
                    "ann_year": year,
                    "surprise": surprise,
                    "surprise_quintile": quintile,
                    "beat": int(surprise > 0),
                    "actual_eps": round(np.random.uniform(0.5, 5.0), 2),
                    "medest": round(np.random.uniform(0.5, 5.0), 2),
                    "numest": int(np.random.randint(5, 35)),
                    "car_m1_p1": round(car_m1_p1, 4),
                    "car_0_p30": round(car_0_30, 4),
                    "car_0_p60": round(car_0_60, 4),
                    "sector": sectors.get(ticker, "Other"),
                    "mkcap_quintile": np.random.choice(["Q1", "Q2", "Q3", "Q4", "Q5"]),
                    "revision_30d": np.random.normal(0.01, 0.05),
                    "revision_60d": np.random.normal(0.02, 0.08),
                    "dispersion": abs(np.random.normal(0.1, 0.05)),
                    "prior_surprise": np.random.normal(0.04, 0.15),
                    "days_since_last": int(np.random.randint(80, 100)),
                    "beat_prob": None,
                })
    df = pd.DataFrame(records)

    # Add synthetic beat probabilities for signal dashboard
    df["beat_prob"] = (
        0.5
        + 0.3 * df["revision_30d"].fillna(0)
        + 0.2 * df["prior_surprise"].fillna(0)
        - 0.1 * df["dispersion"].fillna(0)
    ).clip(0.1, 0.9)
    return df


def _demo_metrics():
    return {
        "model_name": "Random Forest",
        "selected_model": {
            "accuracy": 0.6124,
            "roc_auc": 0.6587,
            "precision": 0.6312,
            "recall": 0.5891,
            "f1": 0.6094,
        },
        "lr": {"accuracy": 0.5934, "roc_auc": 0.6243, "precision": 0.6011, "recall": 0.5744, "f1": 0.5874},
        "rf": {"accuracy": 0.6124, "roc_auc": 0.6587, "precision": 0.6312, "recall": 0.5891, "f1": 0.6094},
        "n_observations": 14_200,
        "beat_rate": 0.568,
    }


def _demo_feat_importance():
    return [
        {"feature": "revision_30d", "importance": 0.28},
        {"feature": "prior_surprise", "importance": 0.22},
        {"feature": "revision_60d", "importance": 0.17},
        {"feature": "dispersion", "importance": 0.12},
        {"feature": "num_analysts", "importance": 0.09},
        {"feature": "sector_encoded", "importance": 0.07},
        {"feature": "mkcap_encoded", "importance": 0.03},
        {"feature": "days_since_last", "importance": 0.02},
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    _load_data()
    log.info("PEAD API started")


@app.get("/api/tickers")
def get_tickers():
    _load_data()
    return {"tickers": _cache["tickers"]}


@app.get("/api/sectors")
def get_sectors():
    _load_data()
    return {"sectors": _cache["sectors"]}


@app.get("/api/data-status")
def data_status():
    _load_data()
    overall = _cache.get("agg_overall") or {}
    return {
        "is_real_data": _cache.get("is_real_data", False),
        "source": overall.get("data_source", "Synthetic Demo Data"),
        "n_events": overall.get("n_events"),
        "n_tickers": overall.get("n_tickers"),
        "sample_start": overall.get("sample_start"),
        "sample_end": overall.get("sample_end"),
    }


@app.post("/api/admin/refresh-data")
def refresh_data(
    background_tasks: BackgroundTasks,
    refresh_raw: bool = Query(False),
    x_refresh_token: Optional[str] = Header(None),
):
    _require_refresh_token(x_refresh_token)

    with _refresh_lock:
        if _refresh_status["state"] in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="A WRDS refresh is already running")
        _refresh_status.update({
            "state": "queued",
            "started_at": None,
            "finished_at": None,
            "refresh_raw": refresh_raw,
            "result": None,
            "error": None,
        })

    background_tasks.add_task(_run_refresh_job, refresh_raw)
    return {
        "status": "queued",
        "refresh_raw": refresh_raw,
        "message": "WRDS refresh queued. Poll /api/admin/refresh-status for progress.",
    }


@app.get("/api/admin/refresh-status")
def refresh_status(x_refresh_token: Optional[str] = Header(None)):
    _require_refresh_token(x_refresh_token)
    with _refresh_lock:
        return dict(_refresh_status)
@app.get("/api/pead-explorer")
def pead_explorer(
    ticker: Optional[str] = Query(None),
    sector: Optional[str] = Query(None),
    start_year: int = Query(2010),
    end_year: int = Query(2023),
):
    _load_data()

    # Use real WRDS aggregates if row-level data isn't available
    if _cache.get("is_real_data") and "df" not in _cache:
        if ticker:
            return _explorer_ticker_from_aggregates(ticker, start_year, end_year)
        return _explorer_from_aggregates(start_year, end_year)

    df = _cache["df"].copy()

    df = df[(df["ann_year"] >= start_year) & (df["ann_year"] <= end_year)]

    if ticker:
        df = df[df["ticker"].str.upper() == ticker.upper()]
        if df.empty:
            raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found")
    elif sector:
        if "sector" in df.columns:
            df = df[df["sector"] == sector]

    if df.empty:
        raise HTTPException(status_code=404, detail="No data found for the selected filters")

    # Surprise timeline
    timeline = (
        df[["anndats", "ticker", "surprise", "surprise_quintile", "beat", "actual_eps", "medest"]]
        .dropna(subset=["surprise"])
        .sort_values("anndats")
    )
    timeline["anndats"] = timeline["anndats"].dt.strftime("%Y-%m-%d")
    timeline_records = timeline.head(500).to_dict(orient="records")

    # Average CAR by quintile
    quintile_order = ["Large Miss", "Miss", "Inline", "Beat", "Large Beat"]
    car_by_quintile = {}
    for q in quintile_order:
        sub = df[df["surprise_quintile"] == q]
        car_by_quintile[q] = {
            "car_m1_p1": _safe_mean(sub["car_m1_p1"]),
            "car_0_p30": _safe_mean(sub["car_0_p30"]),
            "car_0_p60": _safe_mean(sub["car_0_p60"]),
            "n": len(sub),
        }

    # Summary stats
    summary = {
        "n_events": len(df),
        "beat_rate": round(df["beat"].mean(), 3) if len(df) > 0 else None,
        "avg_surprise": round(df["surprise"].mean(), 4) if len(df) > 0 else None,
        "avg_car_0_60": _safe_mean(df["car_0_p60"]),
        "median_analysts": round(df["numest"].median(), 1) if "numest" in df.columns and len(df) > 0 else None,
    }

    return {
        "summary": summary,
        "timeline": timeline_records,
        "car_by_quintile": car_by_quintile,
    }


@app.get("/api/annual-trend")
def annual_trend():
    _load_data()
    return {"annual": _cache.get("agg_annual") or []}


@app.get("/api/backtest")
def backtest(
    quintile: str = Query("Large Beat"),
    hold_days: int = Query(60),
):
    """
    Simulate a long-only strategy: buy stocks in `quintile` the day after
    announcement, hold for `hold_days` trading days. Compare cumulative
    return vs. a buy-and-hold market benchmark (assumed flat daily excess).
    Uses CAR windows already computed in features.csv.
    """
    _load_data()

    # Need row-level data
    df = _cache.get("df")
    if df is None:
        # Fall back to quintile aggregates for a simplified version
        qcar = _cache.get("agg_quintile_car") or []
        q_map = {q["quintile"]: q for q in qcar}
        quintiles = ["Large Miss", "Miss", "Inline", "Beat", "Large Beat"]
        results = []
        cum = 1.0
        mkt_cum = 1.0
        for i, q in enumerate(quintiles):
            row = q_map.get(q, {})
            r = row.get("avg_car_0_p60") or 0
            cum *= (1 + r)
            results.append({
                "quintile": q,
                "avg_car_60": round(r, 4),
                "strategy_cum": round(cum - 1, 4),
            })
        return {"results": results, "is_real_data": False, "note": "Simplified — no row-level data"}

    car_col = "car_0_p60" if hold_days >= 60 else "car_0_p30" if hold_days >= 30 else "car_m1_p1"

    # Filter to requested quintile, sort by date
    sub = df[df["surprise_quintile"] == quintile].dropna(subset=[car_col, "anndats"]).copy()
    if sub.empty:
        raise HTTPException(status_code=404, detail=f"No events found for quintile '{quintile}'")

    sub = sub.sort_values("anndats")
    sub["anndats_str"] = sub["anndats"].dt.strftime("%Y-%m-%d")

    # Build cumulative return series (equal-weight, no compounding across holdings)
    # Each trade = 1 unit of capital, returns car_col
    sub["trade_return"] = pd.to_numeric(sub[car_col], errors="coerce").fillna(0)

    # Annual aggregation for the P&L chart
    sub["year"] = sub["anndats"].dt.year
    annual = sub.groupby("year").agg(
        n_trades=("trade_return", "count"),
        avg_return=("trade_return", "mean"),
        win_rate=("trade_return", lambda x: (x > 0).mean()),
    ).reset_index()

    # Cumulative wealth index
    cum_returns = []
    cum = 1.0
    for _, row in annual.iterrows():
        cum *= (1 + row["avg_return"])
        cum_returns.append({
            "year": int(row["year"]),
            "n_trades": int(row["n_trades"]),
            "avg_return": round(float(row["avg_return"]), 4),
            "win_rate": round(float(row["win_rate"]), 3),
            "cumulative_wealth": round(cum, 4),
        })

    # Summary stats
    total_return = cum - 1
    n_years = len(cum_returns)
    cagr = (cum ** (1 / n_years) - 1) if n_years > 0 else 0
    avg_trade = float(sub["trade_return"].mean())
    win_rate = float((sub["trade_return"] > 0).mean())

    # Compare to market (annual_summary avg CAR is vs market, so market baseline = 0)
    return {
        "quintile": quintile,
        "hold_days": hold_days,
        "n_trades": len(sub),
        "total_return": round(total_return, 4),
        "cagr": round(cagr, 4),
        "avg_trade_return": round(avg_trade, 4),
        "win_rate": round(win_rate, 3),
        "annual": cum_returns,
        "is_real_data": True,
    }


@app.get("/api/methodology")
def methodology():
    _load_data()
    metrics = _cache["metrics"]
    feat_imp = _cache["feat_imp"]

    return {
        "model_name": metrics.get("model_name", "Random Forest"),
        "n_observations": metrics.get("n_observations"),
        "beat_rate": metrics.get("beat_rate"),
        "metrics": metrics.get("selected_model", {}),
        "lr_metrics": metrics.get("lr", {}),
        "rf_metrics": metrics.get("rf", {}),
        "feature_importance": feat_imp,
        "methodology_text": _methodology_text(),
    }


def _methodology_text() -> dict:
    return {
        "what_is_pead": (
            "Post-Earnings Announcement Drift (PEAD) is one of the most well-documented anomalies in financial markets. "
            "When a company reports earnings that are significantly above or below analyst expectations, "
            "the stock price doesn't immediately fully adjust to reflect that information. Instead, "
            "it continues drifting in the direction of the surprise for weeks—sometimes months—afterward. "
            "If a company crushes earnings estimates, the stock tends to keep rising well after the announcement. "
            "If it badly misses, the decline often continues. This contradicts the efficient market hypothesis, "
            "which would predict that all available information is instantly priced in."
        ),
        "why_it_happens": (
            "Researchers attribute PEAD to investor underreaction: analysts are slow to update their models, "
            "institutional investors face constraints that limit how quickly they can act, "
            "and individual investors often don't fully process the implications of an earnings surprise. "
            "The drift is strongest in smaller, less-covered stocks where information diffuses more slowly."
        ),
        "data_sources": (
            "This analysis uses institutional-grade financial data from WRDS (Wharton Research Data Services). "
            "Analyst consensus EPS estimates and actual reported earnings come from IBES (Institutional Brokers' Estimate System). "
            "Daily stock return data comes from CRSP (Center for Research in Security Prices), "
            "and company fundamentals (sector, market cap) come from Compustat. "
            "The sample covers S&P 500 companies from 2010–2023."
        ),
        "earnings_surprise": (
            "Earnings surprise is defined as: (Actual EPS − Consensus Estimate) / |Consensus Estimate|. "
            "A positive value means the company beat expectations; negative means it missed. "
            "We use the most recent median analyst consensus estimate in the 90 days before the announcement. "
            "Announcements are classified into five quintiles from Large Miss to Large Beat."
        ),
        "car_calculation": (
            "Cumulative Abnormal Returns (CAR) measure how much a stock returned above the market benchmark "
            "in a given window around the earnings announcement. Abnormal return = Stock return − Market return (CRSP value-weighted index). "
            "We compute CAR for three windows: [-1, +1] days (immediate reaction), [0, +30] days, and [0, +60] days (the drift)."
        ),
        "ml_model": (
            "The machine learning model predicts whether a company will beat or miss analyst estimates "
            "before the announcement is made. Features are built entirely from pre-announcement data: "
            "how analyst estimates have been revised in the past 30 and 60 days, the spread of estimates across analysts, "
            "the number of analysts covering the stock, the prior quarter's surprise, days since the last report, "
            "sector, and market cap tier. "
            "We train both Logistic Regression and Random Forest with time-series cross-validation—each fold "
            "trains only on historical data, never peeking at the future. The best model is selected by ROC AUC."
        ),
        "disclaimer": (
            "This project is for educational and research purposes only. It is not financial advice, "
            "and nothing here should be interpreted as a recommendation to buy or sell any security. "
            "Past performance of any documented market anomaly does not guarantee future results."
        ),
    }


def _explorer_ticker_from_aggregates(ticker: str, start_year: int, end_year: int) -> dict:
    """Return explorer response for a specific ticker from aggregate data."""
    agg_tickers = _cache.get("agg_tickers") or []
    match = next((t for t in agg_tickers if t["ticker"].upper() == ticker.upper()), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found in dataset")

    quintile_car = _cache.get("agg_quintile_car") or []
    car_by_quintile = {}
    for q in quintile_car:
        car_by_quintile[q["quintile"]] = {
            "car_m1_p1": q.get("avg_car_m1_p1"),
            "car_0_p30": q.get("avg_car_0_p30"),
            "car_0_p60": q.get("avg_car_0_p60"),
            "n": q.get("n"),
        }

    # Synthetic timeline point using aggregate stats for this ticker
    timeline = [{
        "anndats": f"{end_year}-01-01",
        "ticker": match["ticker"],
        "surprise": match.get("avg_surprise"),
        "surprise_quintile": "Beat" if (match.get("avg_surprise") or 0) > 0 else "Miss",
        "beat": 1 if (match.get("avg_surprise") or 0) > 0 else 0,
        "actual_eps": None,
        "medest": None,
    }]

    return {
        "summary": {
            "n_events": match.get("n_events"),
            "beat_rate": match.get("beat_rate"),
            "avg_surprise": match.get("avg_surprise"),
            "avg_car_0_60": match.get("avg_car_0_p60"),
            "median_analysts": match.get("avg_num_analysts"),
        },
        "timeline": timeline,
        "car_by_quintile": car_by_quintile,
        "is_real_data": True,
        "note": f"Showing S&P 500 aggregate CAR by quintile. {match['ticker']} has {match.get('n_events', '?')} events with {round((match.get('beat_rate') or 0)*100)}% beat rate.",
    }


def _explorer_from_aggregates(start_year: int, end_year: int) -> dict:
    """Build explorer response from pre-computed aggregate files (no row-level data)."""
    overall = _cache.get("agg_overall") or {}
    quintile_car = _cache.get("agg_quintile_car") or []
    annual = _cache.get("agg_annual") or []

    # Filter annual to requested range
    annual_filtered = [a for a in annual if start_year <= a["year"] <= end_year]

    # Build a synthetic "timeline" from annual aggregates (no individual events)
    timeline = []
    for a in annual_filtered:
        timeline.append({
            "anndats": f"{a['year']}-01-01",
            "ticker": "S&P 500 Avg",
            "surprise": a.get("avg_surprise"),
            "surprise_quintile": "Beat" if (a.get("avg_surprise") or 0) > 0 else "Miss",
            "beat": 1 if (a.get("avg_surprise") or 0) > 0 else 0,
            "actual_eps": None,
            "medest": None,
        })

    car_by_quintile = {}
    for q in quintile_car:
        car_by_quintile[q["quintile"]] = {
            "car_m1_p1": q.get("avg_car_m1_p1"),
            "car_0_p30": q.get("avg_car_0_p30"),
            "car_0_p60": q.get("avg_car_0_p60"),
            "n": q.get("n"),
        }

    n_filtered = sum(a["n"] for a in annual_filtered)
    beat_vals = [a["beat_rate"] for a in annual_filtered if a.get("beat_rate") is not None]
    car60_vals = [a["avg_car_0_p60"] for a in annual_filtered if a.get("avg_car_0_p60") is not None]

    return {
        "summary": {
            "n_events": n_filtered,
            "beat_rate": round(float(np.mean(beat_vals)), 3) if beat_vals else None,
            "avg_surprise": overall.get("avg_surprise"),
            "avg_car_0_60": round(float(np.mean(car60_vals)), 4) if car60_vals else None,
            "median_analysts": None,
        },
        "timeline": timeline,
        "car_by_quintile": car_by_quintile,
        "is_real_data": True,
    }


@app.get("/api/signal-dashboard")
def signal_dashboard(
    sector: Optional[str] = Query(None),
    n: int = Query(50),
):
    _load_data()

    # Use real ticker aggregates if available
    if _cache.get("is_real_data") and _cache.get("agg_tickers"):
        tickers = _cache["agg_tickers"]
        if sector:
            tickers = [t for t in tickers if t.get("sector") == sector]

        signals = []
        for t in tickers:
            prob = t.get("beat_prob") or t.get("beat_rate") or 0.5

            def signal(p):
                if p >= 0.65: return "likely_beat"
                if p <= 0.35: return "likely_miss"
                return "uncertain"

            signals.append({
                "ticker": t["ticker"],
                "sector": t.get("sector"),
                "anndats": "Aggregated",
                "beat_prob": round(prob, 3),
                "confidence": round(abs(prob - 0.5) * 2, 3),
                "numest": t.get("avg_num_analysts"),
                "mkcap_quintile": t.get("mkcap_quintile"),
                "signal": signal(prob),
                "beat_rate": t.get("beat_rate"),
                "avg_car_0_p60": t.get("avg_car_0_p60"),
                "n_events": t.get("n_events"),
            })

        signals.sort(key=lambda x: abs(x["beat_prob"] - 0.5), reverse=True)
        return {"signals": signals[:n], "is_real_data": True}

    # Demo fallback (original code below)
    return _signal_dashboard_demo(sector, n)


def _signal_dashboard_demo(sector, n):
    df = _cache["df"].copy()
    latest = df.sort_values("anndats").groupby("ticker").last().reset_index()
    if sector and "sector" in latest.columns:
        latest = latest[latest["sector"] == sector]
    if "beat_prob" in latest.columns:
        latest["confidence"] = ((latest["beat_prob"] - 0.5).abs() * 2).round(3)
        latest = latest.sort_values("confidence", ascending=False)
    else:
        latest["beat_prob"] = 0.55
        latest["confidence"] = 0.10
    cols = ["ticker", "sector", "anndats", "beat_prob", "confidence", "mkvalt", "numest", "mkcap_quintile"]
    available = [c for c in cols if c in latest.columns]
    out = latest[available].head(n).copy()
    out["anndats"] = out["anndats"].dt.strftime("%Y-%m-%d") if hasattr(out["anndats"], "dt") else out["anndats"].astype(str)

    def signal(p):
        if p >= 0.65: return "likely_beat"
        if p <= 0.35: return "likely_miss"
        return "uncertain"

    out["signal"] = out["beat_prob"].apply(signal)
    return {"signals": out.to_dict(orient="records"), "is_real_data": False}


def _safe_mean(series) -> Optional[float]:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if len(vals) == 0:
        return None
    return round(float(vals.mean()), 4)


# ---------------------------------------------------------------------------
# Serve frontend
# ---------------------------------------------------------------------------

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse("<h1>PEAD Analysis App</h1><p>Frontend not found.</p>")


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
