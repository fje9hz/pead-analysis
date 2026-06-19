FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source
COPY src/ ./src/
COPY static/ ./static/

# Aggregated WRDS outputs + derived features (safe to ship)
RUN mkdir -p data/processed/aggregates

COPY data/processed/aggregates/ ./data/processed/aggregates/
COPY data/processed/features.csv ./data/processed/features.csv

# Non-root user for security
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
