"""
Train beat/miss classifier using pre-announcement features.
Time-series cross-validation — never trains on future data.

Outputs:
  data/processed/model_metrics.json
  data/processed/model.joblib
  data/processed/feature_importance.csv
"""

import json
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    roc_auc_score,
    f1_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import TimeSeriesSplit

log = logging.getLogger(__name__)

PROC_DIR = Path("data/processed")
FEATURE_COLS = [
    "revision_30d",
    "revision_60d",
    "dispersion",
    "num_analysts",
    "prior_surprise",
    "days_since_last",
    "sector_encoded",
    "mkcap_encoded",
]


def load_features() -> pd.DataFrame:
    path = PROC_DIR / "features.csv"
    if not path.exists():
        raise FileNotFoundError("Run pipeline first: python -m src.data.pipeline")
    df = pd.read_csv(path, low_memory=False)
    df["anndats"] = pd.to_datetime(df["anndats"])
    return df.sort_values("anndats")


def prepare_xy(df: pd.DataFrame):
    df = df.copy()

    # Encode categoricals
    le_sector = LabelEncoder()
    le_mkcap = LabelEncoder()
    df["sector_encoded"] = le_sector.fit_transform(df["sector"].fillna("Unknown"))
    df["mkcap_encoded"] = le_mkcap.fit_transform(
        df["mkcap_quintile"].astype(str).fillna("Q3")
    )

    # Drop rows missing target or all features
    df = df.dropna(subset=["beat"])
    available_features = [c for c in FEATURE_COLS if c in df.columns]
    X = df[available_features].fillna(df[available_features].median(numeric_only=True))
    y = df["beat"].astype(int)

    return X, y, df, available_features, le_sector, le_mkcap


def evaluate(model, X_test, y_test) -> dict:
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1] if hasattr(model, "predict_proba") else y_pred
    return {
        "accuracy": float(round(accuracy_score(y_test, y_pred), 4)),
        "roc_auc": float(round(roc_auc_score(y_test, y_prob), 4)),
        "precision": float(round(precision_score(y_test, y_pred, zero_division=0), 4)),
        "recall": float(round(recall_score(y_test, y_pred, zero_division=0), 4)),
        "f1": float(round(f1_score(y_test, y_pred, zero_division=0), 4)),
    }


def time_series_cv(model, X: pd.DataFrame, y: pd.Series, n_splits: int = 5) -> dict:
    """Walk-forward CV — each fold trains only on past data."""
    tscv = TimeSeriesSplit(n_splits=n_splits)
    fold_metrics = []

    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        X_tr, X_te = X.iloc[train_idx], X.iloc[test_idx]
        y_tr, y_te = y.iloc[train_idx], y.iloc[test_idx]

        if y_tr.nunique() < 2 or len(y_te) < 10:
            continue

        model.fit(X_tr, y_tr)
        metrics = evaluate(model, X_te, y_te)
        metrics["fold"] = fold
        metrics["n_train"] = len(train_idx)
        metrics["n_test"] = len(test_idx)
        fold_metrics.append(metrics)
        log.info(f"  Fold {fold}: AUC={metrics['roc_auc']:.3f} Acc={metrics['accuracy']:.3f}")

    avg = {
        k: float(round(np.mean([m[k] for m in fold_metrics]), 4))
        for k in ["accuracy", "roc_auc", "precision", "recall", "f1"]
    }
    return {"cv_folds": fold_metrics, "cv_mean": avg}


def train():
    log.info("=== Training PEAD Beat/Miss Classifier ===")
    df = load_features()
    X, y, df_clean, feat_names, le_sector, le_mkcap = prepare_xy(df)

    log.info(f"Dataset: {len(X):,} observations | Beat rate: {y.mean():.1%}")

    # --- Logistic Regression ---
    log.info("Training Logistic Regression (time-series CV) ...")
    lr_pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", C=0.5)),
    ])
    lr_results = time_series_cv(lr_pipe, X, y)
    log.info(f"LR CV mean AUC: {lr_results['cv_mean']['roc_auc']:.3f}")

    # --- Random Forest ---
    log.info("Training Random Forest (time-series CV) ...")
    rf_pipe = Pipeline([
        ("clf", RandomForestClassifier(
            n_estimators=200,
            max_depth=6,
            min_samples_leaf=20,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        ))
    ])
    rf_results = time_series_cv(rf_pipe, X, y)
    log.info(f"RF CV mean AUC: {rf_results['cv_mean']['roc_auc']:.3f}")

    # --- Select best model ---
    lr_auc = lr_results["cv_mean"]["roc_auc"]
    rf_auc = rf_results["cv_mean"]["roc_auc"]
    best_name = "Random Forest" if rf_auc >= lr_auc else "Logistic Regression"
    best_pipe = rf_pipe if rf_auc >= lr_auc else lr_pipe
    best_results = rf_results if rf_auc >= lr_auc else lr_results

    log.info(f"Best model: {best_name} (AUC={max(lr_auc, rf_auc):.3f})")

    # Refit on full data
    best_pipe.fit(X, y)

    # Feature importance
    if best_name == "Random Forest":
        clf = best_pipe.named_steps["clf"]
        importances = clf.feature_importances_
    else:
        clf = best_pipe.named_steps["clf"]
        importances = np.abs(clf.coef_[0])

    feat_imp = pd.DataFrame({
        "feature": feat_names,
        "importance": importances / importances.sum(),
    }).sort_values("importance", ascending=False)
    feat_imp.to_csv(PROC_DIR / "feature_importance.csv", index=False)

    # Save model + metadata
    model_bundle = {
        "model": best_pipe,
        "feature_cols": feat_names,
        "le_sector": le_sector,
        "le_mkcap": le_mkcap,
        "model_name": best_name,
    }
    joblib.dump(model_bundle, PROC_DIR / "model.joblib")

    metrics = {
        "model_name": best_name,
        "lr": lr_results["cv_mean"],
        "rf": rf_results["cv_mean"],
        "selected_model": best_results["cv_mean"],
        "n_observations": int(len(X)),
        "beat_rate": float(round(y.mean(), 4)),
        "feature_importance": feat_imp.to_dict(orient="records"),
    }
    with open(PROC_DIR / "model_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    log.info("Model saved to data/processed/model.joblib")
    log.info(f"Final metrics: {metrics['selected_model']}")
    return metrics


def load_model():
    path = PROC_DIR / "model.joblib"
    if not path.exists():
        raise FileNotFoundError("Model not found. Run: python -m src.models.train")
    return joblib.load(path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    train()
