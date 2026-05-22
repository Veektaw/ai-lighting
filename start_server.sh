#!/bin/bash

# ============================================================================
# Server Deployment Script for AI Lighting Project
# Run this script on your server to pull and start the Docker container
# ============================================================================
# Usage: ./start_server.sh [TAG]
# Example: ./start_server.sh latest
# Example: ./start_server.sh v1.0.0
# ============================================================================

set -e  # Exit on error

# Configuration
DOCKER_REPO="turbham/ai-lighting"
CONTAINER_NAME="ai-lighting"
DEFAULT_TAG="latest"
HOST_PORT=8000
CONTAINER_PORT=8000

# Get tag from argument or use default
TAG="${1:-$DEFAULT_TAG}"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  AI Lighting - Server Deployment${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running. Please start Docker and try again.${NC}"
    exit 1
fi

# Stop and remove existing container if it exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${YELLOW}Stopping existing container: ${CONTAINER_NAME}${NC}"
    docker stop "${CONTAINER_NAME}" || true
    echo -e "${YELLOW}Removing existing container: ${CONTAINER_NAME}${NC}"
    docker rm "${CONTAINER_NAME}" || true
    echo ""
fi

# Pull the latest image
echo -e "${GREEN}Pulling image: ${DOCKER_REPO}:${TAG}${NC}"
docker pull "${DOCKER_REPO}:${TAG}"
echo ""

# Create persistent data directory on host
DATA_DIR="./ai-lighting-data"
if [ ! -d "$DATA_DIR" ]; then
    echo -e "${YELLOW}Creating data directory: ${DATA_DIR}${NC}"
    mkdir -p "${DATA_DIR}/dwg"
    mkdir -p "${DATA_DIR}/exports"
    mkdir -p "${DATA_DIR}/annotations"
    mkdir -p "${DATA_DIR}/models"
fi
echo -e "${GREEN}✓ Data directory ready: ${DATA_DIR}${NC}"
echo ""

# Run the container
echo -e "${GREEN}Starting container: ${CONTAINER_NAME}${NC}"
echo -e "${BLUE}Configuration:${NC}"
echo -e "  • Image: ${DOCKER_REPO}:${TAG}"
echo -e "  • Port: ${HOST_PORT}:${CONTAINER_PORT}"
echo -e "  • Data Volume: ${DATA_DIR} → /app/data"
echo -e "  • Container Name: ${CONTAINER_NAME}"
echo ""

docker run -d \
    --name "${CONTAINER_NAME}" \
    --restart unless-stopped \
    -p "${HOST_PORT}:${CONTAINER_PORT}" \
    -v "$(pwd)/${DATA_DIR}/dwg:/app/data/dwg" \
    -v "$(pwd)/${DATA_DIR}/exports:/app/data/exports" \
    -v "$(pwd)/${DATA_DIR}/annotations:/app/data/annotations" \
    -v "$(pwd)/${DATA_DIR}/models:/app/ml/models" \
    -e API_HOST=0.0.0.0 \
    -e API_PORT=8000 \
    "${DOCKER_REPO}:${TAG}"

# Wait for container to start
echo -e "${YELLOW}Waiting for container to start...${NC}"
sleep 3

# Check if container is running
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo ""
    echo -e "${GREEN}================================================${NC}"
    echo -e "${GREEN}  ✓ Container Started Successfully!${NC}"
    echo -e "${GREEN}================================================${NC}"
    echo ""
    echo -e "${BLUE}Container Status:${NC}"
    docker ps --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo ""
    echo -e "${BLUE}Application URLs:${NC}"
    echo -e "  • Frontend: ${GREEN}http://localhost:${HOST_PORT}/${NC}"
    echo -e "  • API Docs: ${GREEN}http://localhost:${HOST_PORT}/docs${NC}"
    echo -e "  • Health:   ${GREEN}http://localhost:${HOST_PORT}/health${NC}"
    echo ""
    echo -e "${BLUE}Useful Commands:${NC}"
    echo -e "  • View logs:      ${YELLOW}docker logs -f ${CONTAINER_NAME}${NC}"
    echo -e "  • Stop container: ${YELLOW}docker stop ${CONTAINER_NAME}${NC}"
    echo -e "  • Start container:${YELLOW}docker start ${CONTAINER_NAME}${NC}"
    echo -e "  • Restart:        ${YELLOW}docker restart ${CONTAINER_NAME}${NC}"
    echo -e "  • Remove:         ${YELLOW}docker rm -f ${CONTAINER_NAME}${NC}"
    echo ""
    echo -e "${YELLOW}Checking health endpoint...${NC}"
    sleep 5
    if curl -f http://localhost:${HOST_PORT}/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Health check passed!${NC}"
    else
        echo -e "${YELLOW}⚠️  Health check failed. Container may still be starting up.${NC}"
        echo -e "${YELLOW}   Check logs: docker logs ${CONTAINER_NAME}${NC}"
    fi
    echo ""
else
    echo ""
    echo -e "${RED}✗ Container failed to start!${NC}"
    echo -e "${YELLOW}Check logs with: docker logs ${CONTAINER_NAME}${NC}"
    exit 1
fi
