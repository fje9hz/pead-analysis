"""
Generate safe, aggregated outputs from the processed WRDS pipeline data.

Inputs:  data/processed/features.csv  (row-level, NOT committed to repo)
Outputs: data/processed/aggregates/   (committed to repo — no row-level data)

Aggregate files produced:
  quintile_car.json      — avg CAR by surprise quintile (5 rows)
  sector_car.json        — avg CAR and beat rate by sector
  ticker_summary.json    — per-ticker stats (beat rate, avg surprise, avg CAR, n_events)
  annual_summary.json    — year-by-year beat rate and avg drift
  model_metrics.json     — already aggregated, copied here for convenience

No individual earnings events, no raw EPS figures, no announcement dates are included.
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

PROC_DIR = Path("data/processed")
AGG_DIR = PROC_DIR / "aggregates"
AGG_DIR.mkdir(parents=True, exist_ok=True)

QUINTILE_ORDER = ["Large Miss", "Miss", "Inline", "Beat", "Large Beat"]


def load_features() -> pd.DataFrame:
    path = PROC_DIR / "features.csv"
    if not path.exists():
        raise FileNotFoundError(
            "data/processed/features.csv not found.\n"
            "Run: python3 -m src.data.wrds_pull && python3 -m src.data.pipeline"
        )
    df = pd.read_csv(path, low_memory=False)
    df["anndats"] = pd.to_datetime(df["anndats"])
    df["ann_year"] = df["anndats"].dt.year
    for col in ["surprise", "car_m1_p1", "car_0_p30", "car_0_p60", "beat"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def safe_mean(s) -> float | None:
    v = pd.to_numeric(s, errors="coerce").dropna()
    return round(float(v.mean()), 4) if len(v) else None

def safe_median(s) -> float | None:
    v = pd.to_numeric(s, errors="coerce").dropna()
    return round(float(v.median()), 4) if len(v) else None


# ── 1. Quintile CAR summary ──────────────────────────────────────────────────

def build_quintile_car(df: pd.DataFrame) -> list[dict]:
    out = []
    for q in QUINTILE_ORDER:
        sub = df[df["surprise_quintile"] == q]
        out.append({
            "quintile": q,
            "n": int(len(sub)),
            "avg_surprise": safe_mean(sub["surprise"]),
            "avg_car_m1_p1": safe_mean(sub["car_m1_p1"]),
            "avg_car_0_p30": safe_mean(sub["car_0_p30"]),
            "avg_car_0_p60": safe_mean(sub["car_0_p60"]),
            "median_car_0_p60": safe_median(sub["car_0_p60"]),
        })
    return out


# ── 2. Sector summary ────────────────────────────────────────────────────────

def build_sector_summary(df: pd.DataFrame) -> list[dict]:
    if "sector" not in df.columns:
        return []
    out = []
    for sector, sub in df.groupby("sector"):
        out.append({
            "sector": sector,
            "n": int(len(sub)),
            "beat_rate": safe_mean(sub["beat"]),
            "avg_surprise": safe_mean(sub["surprise"]),
            "avg_car_0_p60": safe_mean(sub["car_0_p60"]),
            "avg_car_0_p30": safe_mean(sub["car_0_p30"]),
        })
    return sorted(out, key=lambda x: x["n"], reverse=True)


# ── 3. Per-ticker summary (aggregate only — no event-level data) ─────────────

def build_ticker_summary(df: pd.DataFrame) -> list[dict]:
    out = []
    for ticker, sub in df.groupby("ticker"):
        sector = sub["sector"].mode().iloc[0] if "sector" in sub.columns and len(sub) > 0 else None
        mkcap = sub["mkcap_quintile"].mode().iloc[0] if "mkcap_quintile" in sub.columns and len(sub) > 0 else None
        out.append({
            "ticker": ticker,
            "sector": sector,
            "mkcap_quintile": str(mkcap) if mkcap else None,
            "n_events": int(len(sub)),
            "beat_rate": safe_mean(sub["beat"]),
            "avg_surprise": safe_mean(sub["surprise"]),
            "avg_car_0_p60": safe_mean(sub["car_0_p60"]),
            "avg_car_0_p30": safe_mean(sub["car_0_p30"]),
            "avg_num_analysts": safe_mean(sub["numest"]) if "numest" in sub.columns else None,
            "beat_prob": None,  # filled in by model prediction step
        })
    return sorted(out, key=lambda x: x["n_events"], reverse=True)


# ── 4. Annual summary ────────────────────────────────────────────────────────

def build_annual_summary(df: pd.DataFrame) -> list[dict]:
    out = []
    for year, sub in df.groupby("ann_year"):
        out.append({
            "year": int(year),
            "n": int(len(sub)),
            "beat_rate": safe_mean(sub["beat"]),
            "avg_surprise": safe_mean(sub["surprise"]),
            "avg_car_0_p60": safe_mean(sub["car_0_p60"]),
        })
    return sorted(out, key=lambda x: x["year"])


# ── 5. Beat prob from model ──────────────────────────────────────────────────

def add_beat_probabilities(ticker_summary: list[dict]) -> list[dict]:
    """Attach model beat probability to each ticker summary if model exists."""
    model_path = PROC_DIR / "model.joblib"
    feat_path = PROC_DIR / "features.csv"
    if not model_path.exists() or not feat_path.exists():
        return ticker_summary

    try:
        import joblib
        bundle = joblib.load(model_path)
        model = bundle["model"]
        feat_cols = bundle["feature_cols"]
        le_sector = bundle["le_sector"]
        le_mkcap = bundle["le_mkcap"]

        df = load_features()
        df["sector_encoded"] = le_sector.transform(
            df["sector"].fillna("Unknown").map(
                lambda x: x if x in le_sector.classes_ else "Unknown"
            )
        )
        df["mkcap_encoded"] = le_mkcap.transform(
            df["mkcap_quintile"].astype(str).fillna("Q3").map(
                lambda x: x if x in le_mkcap.classes_ else "Q3"
            )
        )

        available = [c for c in feat_cols if c in df.columns]
        X = df[available].fillna(df[available].median(numeric_only=True))
        df["beat_prob"] = model.predict_proba(X)[:, 1]

        # Average per ticker (most recent 4 quarters weighted more)
        ticker_prob = df.sort_values("anndats").groupby("ticker")["beat_prob"].apply(
            lambda s: round(float(np.average(s, weights=np.linspace(0.5, 1.0, len(s)))), 3)
        ).to_dict()

        for item in ticker_summary:
            item["beat_prob"] = ticker_prob.get(item["ticker"])
    except Exception as e:
        log.warning(f"Could not attach beat probabilities: {e}")

    return ticker_summary


# ── Main ─────────────────────────────────────────────────────────────────────

def run():
    log.info("=== Generating safe aggregate outputs ===")
    df = load_features()
    log.info(f"Loaded {len(df):,} observations")

    quintile_car = build_quintile_car(df)
    sector_summary = build_sector_summary(df)
    ticker_summary = build_ticker_summary(df)
    ticker_summary = add_beat_probabilities(ticker_summary)
    annual_summary = build_annual_summary(df)

    overall = {
        "n_events": int(len(df)),
        "n_tickers": int(df["ticker"].nunique()),
        "beat_rate": safe_mean(df["beat"]),
        "avg_surprise": safe_mean(df["surprise"]),
        "avg_car_0_p60": safe_mean(df["car_0_p60"]),
        "sample_start": str(df["anndats"].min().date()),
        "sample_end": str(df["anndats"].max().date()),
        "data_source": "WRDS / IBES / CRSP / Compustat",
        "is_real_data": True,
    }

    outputs = {
        "quintile_car.json": quintile_car,
        "sector_summary.json": sector_summary,
        "ticker_summary.json": ticker_summary,
        "annual_summary.json": annual_summary,
        "overall.json": overall,
    }

    for fname, data in outputs.items():
        path = AGG_DIR / fname
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        log.info(f"Wrote {path}")

    # Copy model metrics
    src = PROC_DIR / "model_metrics.json"
    dst = AGG_DIR / "model_metrics.json"
    if src.exists():
        import shutil
        shutil.copy(src, dst)
        log.info(f"Copied model_metrics.json")

    src_fi = PROC_DIR / "feature_importance.csv"
    dst_fi = AGG_DIR / "feature_importance.csv"
    if src_fi.exists():
        import shutil
        shutil.copy(src_fi, dst_fi)
        log.info(f"Copied feature_importance.csv")

    log.info("Done. Safe to commit data/processed/aggregates/")
    return outputs


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
