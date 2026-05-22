#!/bin/bash

# ============================================================================
# Build and Push Docker Image Script for AI Lighting Project
# ============================================================================
# Usage: ./build_and_push.sh [TAG] [ADDITIONAL_TAG]
# Example: ./build_and_push.sh v1.0.0 latest
# Example: ./build_and_push.sh dev
# ============================================================================

set -e  # Exit on error

# Configuration
DOCKER_REPO="turbham/ai-lighting"
DEFAULT_TAG="latest"

# Get tag from argument or use default
TAG="${1:-$DEFAULT_TAG}"
ADDITIONAL_TAG="${2:-}"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  AI Lighting - Docker Build and Push${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running. Please start Docker and try again.${NC}"
    exit 1
fi

# Check if user is logged in to Docker Hub
echo -e "${YELLOW}Checking Docker Hub authentication...${NC}"
if ! docker info | grep -q "Username"; then
    echo -e "${YELLOW}You are not logged in to Docker Hub.${NC}"
    echo -e "${YELLOW}Please log in with your Docker Hub credentials:${NC}"
    docker login
    echo ""
fi

# Determine which Dockerfile to use
if [ "$TAG" = "dev" ]; then
    DOCKERFILE="Dockerfile.local"
    echo -e "${YELLOW}Using Dockerfile.local for dev build${NC}"
else
    DOCKERFILE="Dockerfile"
    echo -e "${YELLOW}Using Dockerfile for production build${NC}"
fi

# Verify Dockerfile exists
if [ ! -f "$DOCKERFILE" ]; then
    echo -e "${RED}Error: $DOCKERFILE not found!${NC}"
    exit 1
fi

# Show build info
echo ""
echo -e "${BLUE}Build Configuration:${NC}"
echo -e "  Repository: ${DOCKER_REPO}"
echo -e "  Primary Tag: ${TAG}"
if [ -n "$ADDITIONAL_TAG" ]; then
    echo -e "  Additional Tag: ${ADDITIONAL_TAG}"
fi
echo -e "  Dockerfile: ${DOCKERFILE}"
echo ""

# Ask for confirmation
read -p "Proceed with build? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Build cancelled.${NC}"
    exit 0
fi

# Build the Docker image
echo ""
echo -e "${GREEN}Building Docker image: ${DOCKER_REPO}:${TAG}${NC}"
echo -e "${YELLOW}This may take several minutes...${NC}"
echo ""

# Build with progress
docker build -f "${DOCKERFILE}" -t "${DOCKER_REPO}:${TAG}" . --progress=plain

# Check build success
if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ Build completed successfully!${NC}"
else
    echo ""
    echo -e "${RED}✗ Build failed!${NC}"
    exit 1
fi

# Tag with additional tag if provided
if [ -n "$ADDITIONAL_TAG" ]; then
    echo ""
    echo -e "${GREEN}Tagging image with additional tag: ${DOCKER_REPO}:${ADDITIONAL_TAG}${NC}"
    docker tag "${DOCKER_REPO}:${TAG}" "${DOCKER_REPO}:${ADDITIONAL_TAG}"
fi

# Show image info
echo ""
echo -e "${BLUE}Image Information:${NC}"
docker images "${DOCKER_REPO}" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"

# Push the primary tag
echo ""
echo -e "${GREEN}Pushing image to Docker Hub: ${DOCKER_REPO}:${TAG}${NC}"
echo ""
docker push "${DOCKER_REPO}:${TAG}"

# Push the additional tag if provided
if [ -n "$ADDITIONAL_TAG" ]; then
    echo ""
    echo -e "${GREEN}Pushing additional tag to Docker Hub: ${DOCKER_REPO}:${ADDITIONAL_TAG}${NC}"
    echo ""
    docker push "${DOCKER_REPO}:${ADDITIONAL_TAG}"
fi

# Summary
echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  ✓ Build and Push Completed Successfully!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${BLUE}Image(s) pushed:${NC}"
echo -e "  • ${DOCKER_REPO}:${TAG}"
if [ -n "$ADDITIONAL_TAG" ]; then
    echo -e "  • ${DOCKER_REPO}:${ADDITIONAL_TAG}"
fi
echo ""
echo -e "${BLUE}To pull this image on your server:${NC}"
echo -e "  ${YELLOW}docker pull ${DOCKER_REPO}:${TAG}${NC}"
echo ""
echo -e "${BLUE}To run this image:${NC}"
echo -e "  ${YELLOW}docker run -d -p 8000:8000 --name ai-lighting ${DOCKER_REPO}:${TAG}${NC}"
echo ""
echo -e "${BLUE}Or use the start_server.sh script on your server.${NC}"
echo ""
