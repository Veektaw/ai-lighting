# ============================================================================
# Multi-stage Dockerfile for AI Lighting Project
# Bundles React frontend + FastAPI backend into single container
# ============================================================================

# ──────────────────────────────────────────────────────────────────────────
# Stage 1: Build React Frontend
# ──────────────────────────────────────────────────────────────────────────
FROM node:18-alpine AS frontend-builder

WORKDIR /build

# Copy frontend package files
COPY ui/package*.json ./

# Install dependencies
RUN npm ci --only=production

RUN npm ci

# Copy frontend source
COPY ui/ ./

# Build frontend (output to /build/dist)
RUN npm run build

# ──────────────────────────────────────────────────────────────────────────
# Stage 2: Python Backend + Serve Frontend
# ──────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for CAD parsing
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire Python application
COPY . .

# Copy built frontend from previous stage
COPY --from=frontend-builder /build/dist /app/ui/dist

# Create necessary data directories
RUN mkdir -p data/dwg data/exports data/annotations ml/models data/concepts

# Copy concepts data
COPY data/concepts/ /app/data/concepts/

# Expose port
EXPOSE 8000

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV API_HOST=0.0.0.0
ENV API_PORT=8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Start script
COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
