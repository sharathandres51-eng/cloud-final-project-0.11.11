# syntax=docker/dockerfile:1
FROM python:3.13-slim

WORKDIR /app

# Install runtime dependencies only (no dev group)
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" \
    "uvicorn>=0.32.0" \
    "pydantic>=2.9.0"

# Copy source and data files into the image
COPY src/ ./src/
COPY reference_times.json ./reference_times.json

# Make src a package when running uvicorn
ENV PYTHONPATH=/app

EXPOSE 80

# Run uvicorn binding to all interfaces on port 80 for Fargate
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "80"]
