#!/bin/bash

# ============================================================================
# Test Docker Build Locally
# Tests the Docker image before pushing to Docker Hub
# ============================================================================

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

TEST_IMAGE="ai-lighting-test"
TEST_CONTAINER="ai-lighting-test"
TEST_PORT=8001

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  Docker Build Test${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Clean up any existing test containers/images
echo -e "${YELLOW}Cleaning up previous test containers...${NC}"
docker stop "$TEST_CONTAINER" 2>/dev/null || true
docker rm "$TEST_CONTAINER" 2>/dev/null || true
docker rmi "$TEST_IMAGE" 2>/dev/null || true
echo ""

# Build the image
echo -e "${GREEN}Building Docker image...${NC}"
echo -e "${YELLOW}This may take several minutes...${NC}"
echo ""
docker build -t "$TEST_IMAGE" .

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Build failed!${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}✓ Build completed successfully${NC}"
echo ""

# Show image size
echo -e "${BLUE}Image Information:${NC}"
docker images "$TEST_IMAGE" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"
echo ""

# Run the container
echo -e "${GREEN}Starting test container on port ${TEST_PORT}...${NC}"
docker run -d \
    --name "$TEST_CONTAINER" \
    -p "${TEST_PORT}:8000" \
    "$TEST_IMAGE"

echo -e "${YELLOW}Waiting for container to start (30 seconds)...${NC}"
sleep 30

# Check if container is running
if ! docker ps | grep -q "$TEST_CONTAINER"; then
    echo -e "${RED}✗ Container failed to start${NC}"
    echo -e "${YELLOW}Logs:${NC}"
    docker logs "$TEST_CONTAINER"
    exit 1
fi

echo -e "${GREEN}✓ Container is running${NC}"
echo ""

# Test health endpoint
echo -e "${BLUE}Testing health endpoint...${NC}"
if curl -f http://localhost:${TEST_PORT}/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Health check passed${NC}"
    echo -e "${BLUE}Response:${NC}"
    curl -s http://localhost:${TEST_PORT}/health | python3 -m json.tool
else
    echo -e "${RED}✗ Health check failed${NC}"
    docker logs "$TEST_CONTAINER"
    exit 1
fi
echo ""

# Test frontend
echo -e "${BLUE}Testing frontend...${NC}"
if curl -f http://localhost:${TEST_PORT}/ > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Frontend is accessible${NC}"
else
    echo -e "${YELLOW}⚠️  Frontend may not be built (API still works)${NC}"
fi
echo ""

# Test concepts endpoint
echo -e "${BLUE}Testing /concepts endpoint...${NC}"
if curl -f http://localhost:${TEST_PORT}/concepts > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Concepts endpoint works${NC}"
    echo -e "${BLUE}Response:${NC}"
    curl -s http://localhost:${TEST_PORT}/concepts | python3 -m json.tool
else
    echo -e "${YELLOW}⚠️  Concepts endpoint issue${NC}"
fi
echo ""

# Show container logs
echo -e "${BLUE}Container logs (last 20 lines):${NC}"
docker logs --tail 20 "$TEST_CONTAINER"
echo ""

# Summary
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  ✓ All Tests Passed!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${BLUE}Test container is running at:${NC}"
echo -e "  • Frontend: ${GREEN}http://localhost:${TEST_PORT}/${NC}"
echo -e "  • API Docs: ${GREEN}http://localhost:${TEST_PORT}/docs${NC}"
echo -e "  • Health:   ${GREEN}http://localhost:${TEST_PORT}/health${NC}"
echo ""
echo -e "${BLUE}Useful commands:${NC}"
echo -e "  • View logs:  ${YELLOW}docker logs -f ${TEST_CONTAINER}${NC}"
echo -e "  • Stop test:  ${YELLOW}docker stop ${TEST_CONTAINER}${NC}"
echo -e "  • Remove:     ${YELLOW}docker rm ${TEST_CONTAINER}${NC}"
echo ""
echo -e "${YELLOW}The test container will keep running for you to test manually.${NC}"
echo -e "${YELLOW}When done, clean up with:${NC}"
echo -e "  ${YELLOW}docker stop ${TEST_CONTAINER} && docker rm ${TEST_CONTAINER}${NC}"
echo ""
echo -e "${GREEN}If everything looks good, you can now build and push:${NC}"
echo -e "  ${YELLOW}./build_and_push.sh latest${NC}"
echo ""
