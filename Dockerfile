# ARM64 — matches Standard_B2ps_v2 AKS node (Ampere Altra processor)
FROM --platform=linux/arm64 python:3.11-slim

WORKDIR /app

# Set PYTHONPATH so 'from app import config' resolves correctly
ENV PYTHONPATH=/app

# Install dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create mock_data directory — app auto-generates data on first run
RUN mkdir -p mock_data

# Non-root user for security
RUN adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app/main.py", \
  "--server.port=8501", \
  "--server.address=0.0.0.0", \
  "--server.headless=true", \
  "--browser.gatherUsageStats=false"]
