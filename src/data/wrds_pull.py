"""
Pull IBES, CRSP, and Compustat data from WRDS and save locally as CSV files.

Run once: python -m src.data.wrds_pull
Subsequent runs read from data/raw/ unless --refresh flag is passed.
"""

import os
import argparse
import logging
from pathlib import Path

import wrds
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)

WRDS_USERNAME = os.getenv("WRDS_USERNAME", "fje9hz")

START_YEAR = 2010
END_YEAR = 2023


def connect() -> wrds.Connection:
    return wrds.Connection(wrds_username=WRDS_USERNAME)


def pull_ibes_actuals(db: wrds.Connection) -> pd.DataFrame:
    """Annual EPS actuals from IBES."""
    log.info("Pulling IBES actuals ...")
    query = f"""
        SELECT ticker, cusip, anndats, value AS actual_eps, pdicity, curr_act
        FROM ibes.act_epsus
        WHERE pdicity = 'ANN'
          AND curr_act = 'USD'
          AND EXTRACT(YEAR FROM anndats) BETWEEN {START_YEAR} AND {END_YEAR}
    """
    df = db.raw_sql(query, date_cols=["anndats"])
    log.info(f"IBES actuals: {len(df):,} rows")
    return df


def pull_ibes_consensus(db: wrds.Connection) -> pd.DataFrame:
    """Consensus EPS estimates from IBES summary file."""
    log.info("Pulling IBES consensus estimates ...")
    query = f"""
        SELECT ticker, cusip, statpers, fpedats, fpi, medest, meanest,
               stdev, numest, highest, lowest
        FROM ibes.statsumu_epsus
        WHERE fpi = '1'
          AND EXTRACT(YEAR FROM statpers) BETWEEN {START_YEAR - 1} AND {END_YEAR}
    """
    df = db.raw_sql(query, date_cols=["statpers", "fpedats"])
    log.info(f"IBES consensus: {len(df):,} rows")
    return df


def pull_crsp_daily(db: wrds.Connection) -> pd.DataFrame:
    """Daily stock returns and prices from CRSP."""
    log.info("Pulling CRSP daily returns (this may take a few minutes) ...")
    query = f"""
        SELECT a.permno, a.date, a.ret, a.retx, a.prc, a.vol, a.shrout,
               b.cusip, b.ticker, b.comnam, b.siccd, b.exchcd
        FROM crsp.dsf AS a
        JOIN crsp.dsenames AS b
          ON a.permno = b.permno
          AND a.date BETWEEN b.namedt AND b.nameendt
        WHERE EXTRACT(YEAR FROM a.date) BETWEEN {START_YEAR - 1} AND {END_YEAR + 1}
          AND b.shrcd IN (10, 11)
          AND b.exchcd IN (1, 2, 3)
    """
    df = db.raw_sql(query, date_cols=["date"])
    log.info(f"CRSP daily: {len(df):,} rows")
    return df


def pull_crsp_market(db: wrds.Connection) -> pd.DataFrame:
    """Market (value-weighted) daily returns from CRSP indices."""
    log.info("Pulling CRSP market returns ...")
    query = f"""
        SELECT date, vwretd AS mkt_ret, ewretd
        FROM crsp.dsi
        WHERE EXTRACT(YEAR FROM date) BETWEEN {START_YEAR - 1} AND {END_YEAR + 1}
    """
    df = db.raw_sql(query, date_cols=["date"])
    log.info(f"CRSP market: {len(df):,} rows")
    return df


def pull_compustat(db: wrds.Connection) -> pd.DataFrame:
    """Company fundamentals from Compustat."""
    log.info("Pulling Compustat fundamentals ...")
    query = f"""
        SELECT gvkey, cusip, tic, conm, sich, fyr, fyear,
               at, ceq, ni, revt, mkvalt
        FROM comp.funda
        WHERE fyear BETWEEN {START_YEAR - 1} AND {END_YEAR}
          AND indfmt = 'INDL'
          AND datafmt = 'STD'
          AND popsrc = 'D'
          AND consol = 'C'
    """
    df = db.raw_sql(query)
    log.info(f"Compustat: {len(df):,} rows")
    return df


def pull_sp500_constituents(db: wrds.Connection) -> pd.DataFrame:
    """Historical S&P 500 constituents from CRSP."""
    log.info("Pulling S&P 500 constituents ...")
    query = f"""
        SELECT permno, start, ending, co_name
        FROM crsp.dsp500list
        WHERE EXTRACT(YEAR FROM start) <= {END_YEAR}
          AND (ending IS NULL OR EXTRACT(YEAR FROM ending) >= {START_YEAR})
    """
    df = db.raw_sql(query, date_cols=["start", "ending"])
    log.info(f"S&P 500 constituents: {len(df):,} rows")
    return df


def run(refresh: bool = False):
    files = {
        "ibes_actuals": RAW_DIR / "ibes_actuals.csv",
        "ibes_consensus": RAW_DIR / "ibes_consensus.csv",
        "crsp_daily": RAW_DIR / "crsp_daily.csv",
        "crsp_market": RAW_DIR / "crsp_market.csv",
        "compustat": RAW_DIR / "compustat.csv",
        "sp500": RAW_DIR / "sp500_constituents.csv",
    }

    all_exist = all(p.exists() for p in files.values())
    if all_exist and not refresh:
        log.info("All raw data files found. Skipping WRDS pull (use --refresh to re-pull).")
        return

    log.info("Connecting to WRDS ...")
    db = connect()

    pullers = {
        "ibes_actuals": pull_ibes_actuals,
        "ibes_consensus": pull_ibes_consensus,
        "crsp_daily": pull_crsp_daily,
        "crsp_market": pull_crsp_market,
        "compustat": pull_compustat,
        "sp500": pull_sp500_constituents,
    }

    for name, path in files.items():
        if path.exists() and not refresh:
            log.info(f"Skipping {name} (already exists)")
            continue
        df = pullers[name](db)
        df.to_csv(path, index=False)
        log.info(f"Saved {name} -> {path}")

    db.close()
    log.info("WRDS pull complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Re-pull from WRDS even if files exist")
    args = parser.parse_args()
    run(refresh=args.refresh)
