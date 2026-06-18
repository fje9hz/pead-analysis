"""
Run the full WRDS-backed data refresh.

This pulls raw WRDS data, rebuilds processed features, and retrains the model.
"""

import argparse
import logging

from src.data import pipeline, wrds_pull
from src.models import train

log = logging.getLogger(__name__)


def run(refresh_raw: bool = False) -> dict:
    log.info("=== Starting full WRDS refresh ===")
    wrds_pull.run(refresh=refresh_raw)
    features = pipeline.run()
    metrics = train.train()
    log.info("=== WRDS refresh complete ===")
    return {
        "features_rows": int(len(features)),
        "model_name": metrics.get("model_name"),
        "metrics": metrics.get("selected_model", {}),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh-raw",
        action="store_true",
        help="Re-pull raw WRDS files even when cached CSVs already exist.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(refresh_raw=args.refresh_raw)
