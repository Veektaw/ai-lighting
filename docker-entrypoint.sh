#!/bin/bash
# Production entrypoint - starts FastAPI serving both API and static frontend

set -e

echo "================================================"
echo "  AI Lighting Project - Production Mode"
echo "================================================"
echo ""

# Verify directories exist
echo "✓ Checking data directories..."
mkdir -p data/dwg data/exports data/annotations ml/models data/concepts

# Check if frontend build exists
if [ ! -d "ui/dist" ]; then
    echo "⚠️  Warning: Frontend build not found at ui/dist"
    echo "   API will still work, but frontend won't be served"
fi

echo "✓ Data directories ready"
echo "✓ Starting FastAPI server on ${API_HOST:-0.0.0.0}:${API_PORT:-8000}"
echo ""
echo "Server will be available at:"
echo "  - API:      http://localhost:${API_PORT:-8000}"
echo "  - Frontend: http://localhost:${API_PORT:-8000}/ (if built)"
echo "  - Health:   http://localhost:${API_PORT:-8000}/health"
echo ""

# Start the FastAPI server (serving both API and static files)
exec uvicorn services.api.main:app \
    --host "${API_HOST:-0.0.0.0}" \
    --port "${API_PORT:-8000}" \
    --workers 1 \
    --log-level info
