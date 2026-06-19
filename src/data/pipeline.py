"""
Data pipeline: merge IBES/CRSP/Compustat, compute earnings surprise,
calculate cumulative abnormal returns (CAR), build ML feature set.

Outputs written to data/processed/.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
PROC_DIR = Path("data/processed")
PROC_DIR.mkdir(parents=True, exist_ok=True)

# CAR windows (relative trading days around announcement)
CAR_WINDOWS = {
    "car_m1_p1": (-1, 1),
    "car_0_p30": (0, 30),
    "car_0_p60": (0, 60),
}

QUINTILE_LABELS = ["Large Miss", "Miss", "Inline", "Beat", "Large Beat"]


# ---------------------------------------------------------------------------
# Load raw data
# ---------------------------------------------------------------------------

def load_raw() -> dict[str, pd.DataFrame]:
    frames = {}
    for name in ["ibes_actuals", "ibes_consensus", "crsp_daily", "crsp_market", "compustat", "sp500_constituents"]:
        path = RAW_DIR / f"{name}.csv"
        if not path.exists():
            raise FileNotFoundError(
                f"Missing {path}. Run: python -m src.data.wrds_pull"
            )
        frames[name] = pd.read_csv(path, low_memory=False)
    return frames


# ---------------------------------------------------------------------------
# Step 1: Compute earnings surprise
# ---------------------------------------------------------------------------

def compute_surprise(actuals: pd.DataFrame, consensus: pd.DataFrame) -> pd.DataFrame:
    """
    For each announcement, find the most recent consensus estimate
    before the announcement date, compute surprise.
    """
    actuals["anndats"] = pd.to_datetime(actuals["anndats"])
    consensus["statpers"] = pd.to_datetime(consensus["statpers"])
    consensus["fpedats"] = pd.to_datetime(consensus["fpedats"])

    actuals = actuals.dropna(subset=["actual_eps", "ticker", "anndats"])
    consensus = consensus.dropna(subset=["medest", "ticker"])

    # Keep last consensus estimate before each announcement
    merged = pd.merge(
        actuals[["ticker", "cusip", "anndats", "actual_eps"]],
        consensus[["ticker", "statpers", "fpedats", "medest", "meanest", "stdev", "numest"]],
        on="ticker",
        how="inner",
    )
    # Estimate must be before announcement and within 90 days prior
    merged = merged[
        (merged["statpers"] < merged["anndats"]) &
        (merged["statpers"] >= merged["anndats"] - pd.Timedelta(days=90))
    ]

    # Take most recent estimate per announcement
    merged = (
        merged.sort_values("statpers")
        .groupby(["ticker", "anndats"], as_index=False)
        .last()
    )

    # Earnings surprise = (actual - consensus) / |consensus|
    merged["surprise"] = np.where(
        merged["medest"].abs() > 0.01,
        (merged["actual_eps"] - merged["medest"]) / merged["medest"].abs(),
        np.nan,
    )
    merged = merged.dropna(subset=["surprise"])

    # Clip extreme values (data errors / one-time items)
    merged["surprise"] = merged["surprise"].clip(-2.0, 2.0)

    # Surprise quintile — use rank-based cut so duplicate values never break labeling
    merged["surprise_quintile"] = pd.qcut(
        merged["surprise"].rank(method="first"),
        q=5,
        labels=QUINTILE_LABELS,
    )

    # Binary beat/miss
    merged["beat"] = (merged["surprise"] > 0).astype(int)

    log.info(f"Surprise dataset: {len(merged):,} announcement-quarters")
    return merged


# ---------------------------------------------------------------------------
# Step 2: Build event-window stock return panel
# ---------------------------------------------------------------------------

def build_car_panel(
    surprise: pd.DataFrame,
    crsp: pd.DataFrame,
    market: pd.DataFrame,
) -> pd.DataFrame:
    """Compute cumulative abnormal returns for each event window."""
    crsp["date"] = pd.to_datetime(crsp["date"])
    market["date"] = pd.to_datetime(market["date"])

    crsp = crsp.sort_values(["permno", "date"])
    crsp["ret"] = pd.to_numeric(crsp["ret"], errors="coerce")
    market["mkt_ret"] = pd.to_numeric(market["mkt_ret"], errors="coerce")

    # Abnormal return = stock return - market return
    crsp = crsp.merge(market[["date", "mkt_ret"]], on="date", how="left")
    crsp["ab_ret"] = crsp["ret"] - crsp["mkt_ret"]

    # Map ticker -> permno via CUSIP
    cusip_map = (
        crsp[["cusip", "permno", "ticker"]]
        .dropna(subset=["cusip"])
        .drop_duplicates(subset=["cusip", "permno"])
    )
    # Normalize 8-char CUSIP (IBES uses 8, CRSP uses 8 or 9)
    surprise["cusip8"] = surprise["cusip"].str[:8]
    cusip_map["cusip8"] = cusip_map["cusip"].str[:8]

    # Try merging via CUSIP first, then ticker
    surp_mapped = surprise.merge(
        cusip_map[["cusip8", "permno"]].drop_duplicates("cusip8"),
        on="cusip8",
        how="left",
    )
    missing = surp_mapped["permno"].isna()
    if missing.any():
        ticker_map = (
            crsp[["ticker", "permno"]]
            .dropna()
            .drop_duplicates("ticker")
        )
        fill = surp_mapped[missing].drop(columns=["permno"]).merge(
            ticker_map, on="ticker", how="left"
        )
        surp_mapped.loc[missing, "permno"] = fill["permno"].values

    surp_mapped = surp_mapped.dropna(subset=["permno"])
    surp_mapped["permno"] = surp_mapped["permno"].astype(int)

    # Build daily trading calendar per permno
    crsp_idx = crsp.set_index(["permno", "date"])

    records = []
    for _, row in surp_mapped.iterrows():
        permno = int(row["permno"])
        ann_date = row["anndats"]

        if permno not in crsp_idx.index.get_level_values("permno"):
            continue

        stock_data = crsp_idx.loc[permno].reset_index().sort_values("date")
        # Find trading days relative to announcement
        stock_data["t_day"] = (
            stock_data.index - stock_data[stock_data["date"] >= ann_date].index[0]
            if len(stock_data[stock_data["date"] >= ann_date]) > 0
            else np.nan
        )
        # Safer: rank by calendar position of ann_date
        dates = stock_data["date"].values
        ann_idx = np.searchsorted(dates, np.datetime64(ann_date, "D"))
        if ann_idx >= len(dates):
            continue
        stock_data = stock_data.copy()
        stock_data["t_day"] = np.arange(len(stock_data)) - ann_idx

        car_row = {
            "ticker": row["ticker"],
            "anndats": ann_date,
            "permno": permno,
            "surprise": row["surprise"],
            "surprise_quintile": row["surprise_quintile"],
            "beat": row["beat"],
            "medest": row["medest"],
            "actual_eps": row["actual_eps"],
            "numest": row["numest"],
            "stdev": row["stdev"],
        }

        for col, (t_start, t_end) in CAR_WINDOWS.items():
            window = stock_data[
                (stock_data["t_day"] >= t_start) & (stock_data["t_day"] <= t_end)
            ]
            if len(window) == 0:
                car_row[col] = np.nan
            else:
                car_row[col] = (1 + window["ab_ret"].fillna(0)).prod() - 1

        records.append(car_row)

    panel = pd.DataFrame(records)
    log.info(f"CAR panel: {len(panel):,} events with return windows")
    return panel


# ---------------------------------------------------------------------------
# Step 3: Add Compustat fundamentals
# ---------------------------------------------------------------------------

def add_fundamentals(panel: pd.DataFrame, compustat: pd.DataFrame) -> pd.DataFrame:
    compustat = compustat.dropna(subset=["tic", "at", "fyear"])
    compustat["fyear"] = compustat["fyear"].astype(int)
    compustat["ann_year"] = compustat["fyear"]

    panel["ann_year"] = pd.to_datetime(panel["anndats"]).dt.year

    comp_sub = compustat[["tic", "ann_year", "sich", "at", "mkvalt", "ni"]].rename(
        columns={"tic": "ticker", "sich": "sic_code"}
    )
    comp_sub = comp_sub.drop_duplicates(subset=["ticker", "ann_year"])

    panel = panel.merge(comp_sub, on=["ticker", "ann_year"], how="left")

    # Market cap quintile. Some WRDS pulls have repeated or sparse market-cap
    # values, so duplicate quantile edges can reduce the number of bins.
    panel["mkvalt"] = pd.to_numeric(panel["mkvalt"], errors="coerce")
    mkvalt = panel["mkvalt"].fillna(panel["mkvalt"].median())
    mkcap_bins = pd.qcut(mkvalt.rank(method="first"), q=5, labels=False)
    panel["mkcap_quintile"] = mkcap_bins.apply(
        lambda b: f"Q{int(b) + 1}" if pd.notna(b) else pd.NA
    )

    # Broad sector from SIC code
    panel["sic_code"] = pd.to_numeric(panel["sic_code"], errors="coerce")
    panel["sector"] = panel["sic_code"].apply(_sic_to_sector)

    log.info(f"Panel with fundamentals: {len(panel):,} rows")
    return panel


def _sic_to_sector(sic):
    if pd.isna(sic):
        return "Unknown"
    sic = int(sic)
    if sic < 1000:
        return "Agriculture"
    elif sic < 1500:
        return "Mining"
    elif sic < 2000:
        return "Construction"
    elif sic < 4000:
        return "Manufacturing"
    elif sic < 5000:
        return "Transportation"
    elif sic < 5200:
        return "Wholesale"
    elif sic < 6000:
        return "Retail"
    elif sic < 6500:
        return "Finance"
    elif sic < 7000:
        return "Real Estate"
    elif sic < 8000:
        return "Services"
    elif sic < 9000:
        return "Professional"
    else:
        return "Public"


# ---------------------------------------------------------------------------
# Step 4: Build ML feature set
# ---------------------------------------------------------------------------

def build_features(panel: pd.DataFrame, consensus: pd.DataFrame) -> pd.DataFrame:
    """
    Engineer features from pre-announcement analyst estimate data.
    Features:
    - revision_30d, revision_60d: % change in median estimate over 30/60 days before announcement
    - dispersion: stdev / |medest| (normalized)
    - num_analysts: number of analysts
    - prior_surprise: prior quarter's surprise
    - days_since_last_earnings: trading days since prior announcement
    - sector (categorical)
    - mkcap_quintile (categorical)
    """
    consensus["statpers"] = pd.to_datetime(consensus["statpers"])
    consensus["medest"] = pd.to_numeric(consensus["medest"], errors="coerce")
    consensus = consensus.dropna(subset=["ticker", "statpers", "medest"])
    consensus = consensus.sort_values(["ticker", "statpers"])

    features = []
    panel_sorted = panel.sort_values(["ticker", "anndats"])

    for _, row in panel_sorted.iterrows():
        ticker = row["ticker"]
        ann_date = pd.Timestamp(row["anndats"])

        stock_est = consensus[consensus["ticker"] == ticker].copy()
        pre = stock_est[stock_est["statpers"] < ann_date]

        # Most recent estimate
        if len(pre) == 0:
            features.append({**row.to_dict(), "revision_30d": np.nan, "revision_60d": np.nan,
                              "dispersion": np.nan, "num_analysts": np.nan})
            continue

        recent = pre.iloc[-1]
        est_30d_ago = pre[pre["statpers"] >= ann_date - pd.Timedelta(days=30)]
        est_60d_ago = pre[pre["statpers"] >= ann_date - pd.Timedelta(days=60)]

        def revision(subset, baseline):
            if len(subset) == 0 or abs(baseline) < 0.01:
                return np.nan
            earliest = subset.iloc[0]["medest"]
            return (baseline - earliest) / abs(earliest) if abs(earliest) > 0.01 else np.nan

        baseline_est = recent["medest"]
        rev30 = revision(est_30d_ago, baseline_est)
        rev60 = revision(est_60d_ago, baseline_est)
        disp = (recent["stdev"] / abs(baseline_est)) if abs(baseline_est) > 0.01 else np.nan

        feat = {
            **row.to_dict(),
            "revision_30d": rev30,
            "revision_60d": rev60,
            "dispersion": pd.to_numeric(disp, errors="coerce"),
            "num_analysts": pd.to_numeric(recent["numest"], errors="coerce"),
        }
        features.append(feat)

    feat_df = pd.DataFrame(features)

    # Prior quarter surprise
    feat_df = feat_df.sort_values(["ticker", "anndats"])
    feat_df["prior_surprise"] = feat_df.groupby("ticker")["surprise"].shift(1)

    # Days since last earnings
    feat_df["prev_ann"] = feat_df.groupby("ticker")["anndats"].shift(1)
    feat_df["days_since_last"] = (
        pd.to_datetime(feat_df["anndats"]) - pd.to_datetime(feat_df["prev_ann"])
    ).dt.days

    log.info(f"Feature set: {len(feat_df):,} observations")
    return feat_df


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run():
    log.info("=== PEAD Data Pipeline ===")
    raw = load_raw()

    log.info("Step 1: Computing earnings surprise ...")
    surprise = compute_surprise(raw["ibes_actuals"], raw["ibes_consensus"])
    surprise.to_csv(PROC_DIR / "surprise.csv", index=False)

    log.info("Step 2: Computing cumulative abnormal returns ...")
    panel = build_car_panel(surprise, raw["crsp_daily"], raw["crsp_market"])
    panel.to_csv(PROC_DIR / "car_panel.csv", index=False)

    log.info("Step 3: Adding company fundamentals ...")
    panel = add_fundamentals(panel, raw["compustat"])

    log.info("Step 4: Building ML feature set ...")
    features = build_features(panel, raw["ibes_consensus"])
    features.to_csv(PROC_DIR / "features.csv", index=False)

    log.info("Pipeline complete. Files written to data/processed/")
    return features


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
