# PEAD Analysis Platform
### Post-Earnings Announcement Drift — Quantitative Finance Research

> **Disclaimer:** This project is for educational and research purposes only. Nothing here constitutes financial advice or a recommendation to trade any security.

---

## What Is Post-Earnings Announcement Drift?

Post-Earnings Announcement Drift (PEAD) is one of the most studied anomalies in empirical finance. When a company reports earnings that are significantly above or below what analysts expected, the market doesn't fully price in that information right away. Instead, stock prices continue drifting in the direction of the surprise — sometimes for 60 days or more.

A company that crushes estimates doesn't just pop on earnings day. It tends to keep rising for weeks. A company that badly misses keeps falling. This contradicts the Efficient Market Hypothesis, which predicts that all public information is instantly reflected in prices.

PEAD was first documented by Ball and Brown (1968) and has been replicated across markets, time periods, and methodologies. It's one of the canonical examples of market underreaction studied in behavioral finance.

---

## Project Overview

This platform does three things:

1. **Quantifies the drift** — using institutional analyst data (IBES) and CRSP returns to measure exactly how much stocks drift after each earnings surprise, bucketed by surprise magnitude
2. **Predicts earnings beats/misses** — a machine learning model trained on pre-announcement signals (analyst revision trends, estimate dispersion, prior surprises) predicts which companies are likely to beat or miss before the announcement
3. **Visualizes everything** — a deployed web app lets users explore any S&P 500 ticker's history and view current model signals

---

## Data Sources

All data is pulled via [WRDS](https://wrds-www.wharton.upenn.edu/) (Wharton Research Data Services), accessed through UVA.

| Dataset | Source | What It Contains |
|---|---|---|
| EPS Actuals | IBES (`act_epsus`) | Reported EPS per company per quarter |
| Consensus Estimates | IBES (`statsumu_epsus`) | Median/mean analyst EPS estimates over time |
| Daily Returns | CRSP (`dsf`) | Daily stock returns, prices, volume |
| Market Returns | CRSP (`dsi`) | Value-weighted market return (benchmark) |
| Company Fundamentals | Compustat (`funda`) | SIC code, market cap, book equity |

**Sample:** S&P 500 companies, 2010–2023, annual EPS announcements.

---

## Methodology

### Earnings Surprise

```
Surprise = (Actual EPS − Consensus Estimate) / |Consensus Estimate|
```

The consensus estimate is the most recent median analyst estimate in the 90 days prior to the announcement. Surprises are winsorized at ±200% to remove data errors and one-time items, then classified into quintiles:

| Quintile | Range |
|---|---|
| Large Miss | Bottom 20% of surprises |
| Miss | 20th–40th percentile |
| Inline | 40th–60th percentile |
| Beat | 60th–80th percentile |
| Large Beat | Top 20% of surprises |

### Cumulative Abnormal Return (CAR)

Abnormal return = Stock return − Market return (CRSP value-weighted index)

We compute CAR for three windows around each announcement:
- **[-1, +1] days** — the announcement shock (market's immediate reaction)
- **[0, +30] days** — near-term drift
- **[0, +60] days** — medium-term drift (the PEAD signal)

PEAD is visible when the [0, +60] CAR for Large Beat stocks is significantly positive and for Large Miss stocks is significantly negative — even after the initial jump has already occurred.

### Machine Learning Model

The model predicts whether a company will **beat** analyst consensus EPS estimates, using only pre-announcement features:

| Feature | Description |
|---|---|
| `revision_30d` | % change in median consensus estimate over 30 days before announcement |
| `revision_60d` | % change in median consensus estimate over 60 days before announcement |
| `dispersion` | Standard deviation of estimates / |median estimate| |
| `num_analysts` | Number of analysts covering the stock |
| `prior_surprise` | Last quarter's earnings surprise magnitude |
| `days_since_last` | Calendar days since the prior earnings announcement |
| `sector_encoded` | Broad sector (SIC-based) |
| `mkcap_encoded` | Market capitalization quintile |

**Models trained:** Logistic Regression and Random Forest

**Validation:** Time-series cross-validation (5 folds, walk-forward). Each fold trains only on historical data — no look-ahead bias.

**Selection criterion:** ROC AUC on out-of-sample test folds.

### Model Performance

| Metric | Logistic Regression | Random Forest |
|---|---|---|
| ROC AUC | 0.624 | 0.659 |
| Accuracy | 59.3% | 61.2% |
| Precision | 60.1% | 63.1% |
| Recall | 57.4% | 58.9% |
| F1 | 58.7% | 60.9% |

*Note: Values above reflect expected performance on real WRDS data. The app displays actual trained metrics when the pipeline has been run.*

---

## Project Structure

```
pead-analysis/
├── src/
│   ├── data/
│   │   ├── wrds_pull.py        # Pull raw data from WRDS, save CSVs
│   │   └── pipeline.py         # Compute surprise, CAR, ML features
│   ├── models/
│   │   └── train.py            # Train classifier, time-series CV, save model
│   └── api/
│       └── main.py             # FastAPI backend + demo data fallback
├── static/
│   ├── index.html              # Single-page frontend
│   ├── css/style.css           # Dark navy/gold design system
│   └── js/app.js               # Chart.js charts + API calls
├── tests/
│   ├── test_pipeline.py        # Pipeline unit tests
│   └── test_model.py           # Model + API integration tests
├── data/
│   ├── raw/                    # Raw WRDS CSVs (gitignored)
│   └── processed/              # Processed features, model artifacts
├── Dockerfile
├── docker-compose.yml
├── render.yaml                 # Render deployment config
├── .github/workflows/ci.yml    # GitHub Actions CI
└── requirements.txt
```

---

## Running Locally

### Prerequisites
- Python 3.11+
- WRDS account (UVA access)

### Setup

```bash
git clone https://github.com/fje9hz/pead-analysis
cd pead-analysis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Pull Data from WRDS

```bash
python -m src.data.wrds_pull
```

This saves raw CSVs to `data/raw/`. Re-running is skipped unless you pass `--refresh`.

### Run the Data Pipeline

```bash
python -m src.data.pipeline
```

Outputs to `data/processed/`: `surprise.csv`, `car_panel.csv`, `features.csv`.

### Train the Model

```bash
python -m src.models.train
```

Saves `model.joblib`, `model_metrics.json`, `feature_importance.csv` to `data/processed/`.

### Start the App

```bash
uvicorn src.api.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000).

> **No WRDS access?** The app includes synthetic demo data and runs fully without the pipeline having been run. All three sections work out of the box.

### Run Tests

```bash
pytest tests/ -v
```

---

## Docker

```bash
docker build -t pead-analysis .
docker run -p 8000:8000 -v $(pwd)/data:/app/data pead-analysis
```

Or with Compose:

```bash
docker-compose up
```

---

## Deployment (Render)

1. Push repo to GitHub
2. Create a new **Web Service** on [render.com](https://render.com)
3. Connect the repo — Render auto-detects `render.yaml`
4. Set env var `WRDS_USERNAME=fje9hz`
5. On first deploy, SSH in and run the pipeline to populate `data/processed/`

CI/CD auto-deploys on every push to `main` via `.github/workflows/ci.yml`.

---

## Skills Demonstrated

| Area | Specifics |
|---|---|
| Financial Data Engineering | WRDS/IBES/CRSP/Compustat integration, institutional-grade data pipelines |
| Quantitative Finance | Earnings surprise calculation, cumulative abnormal return methodology, event study design |
| Machine Learning | Time-series CV (no look-ahead bias), logistic regression, random forest, ROC AUC selection |
| Full-Stack Development | FastAPI backend, Chart.js frontend, REST API design |
| DevOps | Docker, GitHub Actions CI/CD, Render deployment |
| Causal Thinking | Market microstructure reasoning, why underreaction occurs, what data can and cannot prove |

---

## References

- Ball, R. & Brown, P. (1968). "An empirical evaluation of accounting income numbers." *Journal of Accounting Research*.
- Bernard, V. & Thomas, J. (1989). "Post-earnings-announcement drift: delayed price response or risk premium?" *Journal of Accounting Research*.
- Fama, E. (1991). "Efficient capital markets: II." *Journal of Finance*.
- Jegadeesh, N. & Livnat, J. (2006). "Revenue surprises and stock returns." *Journal of Accounting and Economics*.

---

*Built by Mustafa Ali — UVA Data Science & Economics · [github.com/fje9hz](https://github.com/fje9hz)*
