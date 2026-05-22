# 🐳 Docker Deployment Guide

## Overview

This project is containerized with Docker and can be deployed to any server. The Docker image includes both the React frontend and Python FastAPI backend in a single container.

**Docker Hub Repository:** `turbham/ai-lighting`

---

## 📦 What's Included

- **Dockerfile** - Production multi-stage build (React + Python)
- **Dockerfile.local** - Development build with hot-reload
- **docker-compose.yml** - Easy orchestration
- **build_and_push.sh** - Build and push to Docker Hub
- **start_server.sh** - Deploy on your server
- **docker-entrypoint.sh** - Production startup script
- **docker-entrypoint-dev.sh** - Development startup script

---

## 🚀 Quick Start (3 Steps)

### 1️⃣ Build and Push (from your local machine)

```bash
# Build production image and push to Docker Hub
./build_and_push.sh latest

# Or build with version tag
./build_and_push.sh v1.0.0 latest

# Build dev image for testing
./build_and_push.sh dev
```

### 2️⃣ Deploy to Server

Copy `start_server.sh` and `docker-compose.yml` to your server, then:

```bash
# Option A: Using the start script
./start_server.sh latest

# Option B: Using docker-compose
docker-compose up -d

# Option C: Manual docker run
docker run -d \
  --name ai-lighting \
  --restart unless-stopped \
  -p 8000:8000 \
  -v $(pwd)/ai-lighting-data:/app/data \
  turbham/ai-lighting:latest
```

### 3️⃣ Access Your App

- **Frontend:** http://your-server:8000/
- **API Docs:** http://your-server:8000/docs
- **Health Check:** http://your-server:8000/health

---

## 📋 Detailed Instructions

### Building the Docker Image

The `build_and_push.sh` script handles everything:

```bash
# Usage: ./build_and_push.sh [TAG] [ADDITIONAL_TAG]

# Examples:
./build_and_push.sh latest              # Build and push 'latest' tag
./build_and_push.sh v1.2.3 latest       # Build v1.2.3 and also tag as latest
./build_and_push.sh dev                 # Build dev version (uses Dockerfile.local)
```

**What the script does:**
1. ✅ Checks Docker is running
2. ✅ Verifies Docker Hub authentication
3. ✅ Builds the image (multi-stage build)
4. ✅ Tags with specified version(s)
5. ✅ Pushes to Docker Hub
6. ✅ Shows summary and pull command

### Manual Build (without script)

```bash
# Production build
docker build -t turbham/ai-lighting:latest .

# Development build
docker build -f Dockerfile.local -t turbham/ai-lighting:dev .

# Push to Docker Hub
docker login
docker push turbham/ai-lighting:latest
```

---

## 🖥️ Server Deployment

### Using the Start Script (Recommended)

The `start_server.sh` script automates deployment:

```bash
# Copy to your server
scp start_server.sh docker-compose.yml user@your-server:~/

# SSH into server and run
ssh user@your-server
./start_server.sh latest
```

**What the script does:**
1. ✅ Checks Docker is running
2. ✅ Stops existing container (if any)
3. ✅ Pulls latest image from Docker Hub
4. ✅ Creates persistent data directories
5. ✅ Starts container with proper volumes
6. ✅ Verifies health endpoint
7. ✅ Shows status and useful commands

### Using Docker Compose

```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Update to latest image
docker-compose pull
docker-compose up -d
```

### Manual Deployment

```bash
# Pull image
docker pull turbham/ai-lighting:latest

# Create data directory
mkdir -p ai-lighting-data/{dwg,exports,annotations,models}

# Run container
docker run -d \
  --name ai-lighting \
  --restart unless-stopped \
  -p 8000:8000 \
  -v $(pwd)/ai-lighting-data/dwg:/app/data/dwg \
  -v $(pwd)/ai-lighting-data/exports:/app/data/exports \
  -v $(pwd)/ai-lighting-data/annotations:/app/data/annotations \
  -v $(pwd)/ai-lighting-data/models:/app/ml/models \
  -e API_HOST=0.0.0.0 \
  -e API_PORT=8000 \
  turbham/ai-lighting:latest

# Check status
docker ps
docker logs ai-lighting

# Test health endpoint
curl http://localhost:8000/health
```

---

## 💾 Data Persistence

The container uses **volumes** for persistent data storage:

| Host Path | Container Path | Purpose |
|-----------|----------------|---------|
| `./ai-lighting-data/dwg` | `/app/data/dwg` | Uploaded DWG/PDF plans |
| `./ai-lighting-data/exports` | `/app/data/exports` | Generated exports |
| `./ai-lighting-data/annotations` | `/app/data/annotations` | Training annotations |
| `./ai-lighting-data/models` | `/app/ml/models` | ML models |

**Important:** These directories are created automatically by `start_server.sh` or `docker-compose.yml`.

---

## 🔧 Management Commands

### View Logs
```bash
docker logs -f ai-lighting           # Follow logs
docker logs --tail 100 ai-lighting   # Last 100 lines
```

### Container Control
```bash
docker start ai-lighting     # Start stopped container
docker stop ai-lighting      # Stop running container
docker restart ai-lighting   # Restart container
docker rm -f ai-lighting     # Remove container
```

### Update to Latest Version
```bash
# Method 1: Using start_server.sh
./start_server.sh latest

# Method 2: Manual
docker stop ai-lighting
docker rm ai-lighting
docker pull turbham/ai-lighting:latest
docker run -d --name ai-lighting ... turbham/ai-lighting:latest

# Method 3: Using docker-compose
docker-compose pull
docker-compose up -d
```

### Access Container Shell
```bash
docker exec -it ai-lighting /bin/bash

# Inside container:
ls /app                    # View app files
ls /app/data/dwg          # View uploaded files
python main.py --help     # Run CLI commands
```

### View Resource Usage
```bash
docker stats ai-lighting
```

---

## 🌐 Network Configuration

### Change Port

Edit the port mapping when running:

```bash
# Use port 80 instead of 8000
docker run -d -p 80:8000 --name ai-lighting turbham/ai-lighting:latest

# Or in docker-compose.yml:
ports:
  - "80:8000"
```

### Behind Reverse Proxy (Nginx)

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 🧪 Testing Locally

### Test Production Build Locally

```bash
# Build without pushing
docker build -t ai-lighting-test .

# Run locally
docker run -d -p 8000:8000 --name ai-lighting-test ai-lighting-test

# Test
curl http://localhost:8000/health
open http://localhost:8000

# Clean up
docker stop ai-lighting-test
docker rm ai-lighting-test
```

### Test Development Build

```bash
# Build dev image
docker build -f Dockerfile.local -t ai-lighting-dev .

# Run with hot-reload
docker run -d -p 8000:8000 -p 3000:3000 \
  -v $(pwd):/app \
  --name ai-lighting-dev \
  ai-lighting-dev

# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
```

---

## 🐛 Troubleshooting

### Container won't start

```bash
# Check logs
docker logs ai-lighting

# Common issues:
# 1. Port already in use
docker ps -a | grep 8000
sudo lsof -i :8000

# 2. Permission issues with volumes
sudo chown -R $(whoami):$(whoami) ai-lighting-data/

# 3. Image not pulled
docker pull turbham/ai-lighting:latest
```

### Health check failing

```bash
# Wait 30 seconds for app to start
sleep 30

# Test health endpoint
curl http://localhost:8000/health

# If still failing, check logs
docker logs ai-lighting
```

### Frontend not loading

```bash
# Verify frontend was built in image
docker exec ai-lighting ls -la /app/ui/dist/

# If empty, rebuild image
./build_and_push.sh latest
```

### Out of disk space

```bash
# Clean old images
docker image prune -a

# Clean stopped containers
docker container prune

# Clean volumes (BE CAREFUL!)
docker volume prune
```

---

## 🔒 Security Recommendations

### For Production:

1. **Use specific version tags** instead of `latest`
   ```bash
   docker pull turbham/ai-lighting:v1.0.0
   ```

2. **Restrict CORS** in production (edit `services/api/main.py`):
   ```python
   app.add_middleware(CORSMiddleware, 
       allow_origins=["https://your-domain.com"],
       allow_methods=["*"], allow_headers=["*"])
   ```

3. **Use environment secrets** for sensitive data:
   ```bash
   docker run -d --env-file .env turbham/ai-lighting:latest
   ```

4. **Run behind HTTPS** with Nginx/Caddy reverse proxy

5. **Set resource limits**:
   ```bash
   docker run -d --memory="2g" --cpus="2" turbham/ai-lighting:latest
   ```

---

## 📊 Monitoring

### Add Logging

```bash
# View all logs
docker logs ai-lighting

# Follow logs in real-time
docker logs -f ai-lighting

# Export logs to file
docker logs ai-lighting > app.log 2>&1
```

### Health Monitoring Script

Create `health-check.sh`:
```bash
#!/bin/bash
if curl -f http://localhost:8000/health > /dev/null 2>&1; then
    echo "✓ Service is healthy"
else
    echo "✗ Service is down - restarting..."
    docker restart ai-lighting
fi
```

Add to crontab:
```bash
*/5 * * * * /path/to/health-check.sh
```

---

## 📦 Image Details

### Production Image (Dockerfile)

- **Base:** python:3.11-slim
- **Size:** ~800MB-1.5GB (depends on dependencies)
- **Includes:**
  - React frontend (built)
  - Python backend
  - All dependencies
  - Data directories
  - Health checks

### Dev Image (Dockerfile.local)

- **Base:** python:3.11-slim + Node.js
- **Size:** ~1.2GB-2GB
- **Features:**
  - Hot reload for both frontend and backend
  - Development tools
  - Larger but faster for development

---

## ❓ FAQ

**Q: Can I use a different port?**  
A: Yes, use `-p YOUR_PORT:8000` when running the container.

**Q: How do I update the app?**  
A: Build and push a new image, then run `./start_server.sh latest` on your server.

**Q: Where is the data stored?**  
A: In volumes mapped to `./ai-lighting-data/` on your host.

**Q: Can I run multiple instances?**  
A: Yes, but use different names and ports:
```bash
docker run -d -p 8001:8000 --name ai-lighting-2 turbham/ai-lighting:latest
```

**Q: How do I backup the data?**  
A: Simply backup the `ai-lighting-data/` directory:
```bash
tar -czf backup-$(date +%Y%m%d).tar.gz ai-lighting-data/
```

**Q: Does it work on ARM (Apple Silicon)?**  
A: Yes! Docker will build for your architecture. For cross-platform builds, use:
```bash
docker buildx build --platform linux/amd64,linux/arm64 -t turbham/ai-lighting:latest .
```

---

## 🎯 Next Steps

1. ✅ Build and push your image: `./build_and_push.sh latest`
2. ✅ Deploy to server: `./start_server.sh latest`
3. ✅ Set up reverse proxy (optional)
4. ✅ Configure SSL/HTTPS (recommended)
5. ✅ Set up monitoring and backups
6. ✅ Configure resource limits for production

---

## 📚 Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/)
- [Vite Production Build](https://vitejs.dev/guide/build.html)

---

**Need help?** Check the logs: `docker logs ai-lighting`
