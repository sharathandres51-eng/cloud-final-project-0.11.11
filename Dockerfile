# syntax=docker/dockerfile:1

# ── Base image ────────────────────────────────────────────────────────────────
FROM python:3.13-slim

# ── Install uv ────────────────────────────────────────────────────────────────
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# ── Set working directory ─────────────────────────────────────────────────────
WORKDIR /app

# ── Install only app-runtime dependencies ─────────────────────────────────────
RUN uv pip install --system --no-cache \
    streamlit \
    xgboost \
    scikit-learn \
    pandas \
    pyarrow \
    boto3

# ── Copy only what the app needs (no models/ — inference is via SageMaker) ───
COPY src/ ./src/
COPY app/ ./app/
COPY models/model_metadata.json ./models/model_metadata.json
COPY data/gold/ ./data/gold/

# ── Make the vaultech_analysis package importable ─────────────────────────────
ENV PYTHONPATH=/app/src

# ── Expose Streamlit port ─────────────────────────────────────────────────────
EXPOSE 8501

# ── Run the app ───────────────────────────────────────────────────────────────
CMD ["streamlit", "run", "app/streamlit_app.py", \
     "--server.address=0.0.0.0", "--server.port=8501"]
