FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for persistent data
RUN mkdir -p /data/aurelius_memory

# Environment defaults (override with docker run -e or docker-compose)
ENV CHROMA_DB_PATH=/data/aurelius_memory
ENV DASHBOARD_PORT=5000
ENV POLL_INTERVAL_MIN=15

# Expose dashboard port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:5000/api/data || exit 1

# Run dashboard (which also starts the scheduler thread)
CMD ["python", "dashboard.py"]
