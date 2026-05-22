#!/bin/bash
# Development entrypoint - runs both frontend dev server and backend

set -e

echo "================================================"
echo "  AI Lighting Project - Development Mode"
echo "================================================"
echo ""
echo "Starting services..."
echo "  - Backend:  http://localhost:8000"
echo "  - Frontend: http://localhost:3000"
echo ""

# Create data directories
mkdir -p data/dwg data/exports data/annotations ml/models

# Start backend in background
cd /app
uvicorn services.api.main:app --host 0.0.0.0 --port 8000 --reload &

# Start frontend dev server
cd /app/ui
npm run dev &

# Wait for both processes
wait
