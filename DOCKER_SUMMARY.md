# 📦 Docker Deployment Summary

## ✅ Created Files

### Docker Configuration
- **[Dockerfile](Dockerfile)** - Production multi-stage build (React + Python)
- **[Dockerfile.local](Dockerfile.local)** - Development build with hot-reload
- **[.dockerignore](.dockerignore)** - Optimize build by excluding unnecessary files
- **[docker-compose.yml](docker-compose.yml)** - Easy orchestration with volumes

### Scripts (All executable ✓)
- **[build_and_push.sh](build_and_push.sh)** - Build image and push to Docker Hub
- **[start_server.sh](start_server.sh)** - Deploy and run on your server
- **[test_docker.sh](test_docker.sh)** - Test build locally before pushing
- **[docker-entrypoint.sh](docker-entrypoint.sh)** - Production container startup
- **[docker-entrypoint-dev.sh](docker-entrypoint-dev.sh)** - Development container startup

### Documentation
- **[DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md)** - Complete deployment guide
- **[DOCKER_QUICK_REF.md](DOCKER_QUICK_REF.md)** - Quick reference card
- **[.env.docker.example](.env.docker.example)** - Environment variables template

### Updated Files
- **[services/api/main.py](services/api/main.py)** - Now serves React static files
- **[README.md](README.md)** - Added Docker deployment section
- **[.gitignore](.gitignore)** - Excludes Docker artifacts

---

## 🚀 How It Works

### Architecture
The Docker image bundles both frontend and backend into a **single container**:

1. **Build Stage 1** (Node.js): Builds React frontend → `ui/dist/`
2. **Build Stage 2** (Python): Installs backend + copies built frontend
3. **Runtime**: FastAPI serves both API endpoints and static frontend

### Single Port Deployment
- **Port 8000** serves everything:
  - Frontend: `http://localhost:8000/`
  - API: `http://localhost:8000/health`, `/process`, etc.
  - API Docs: `http://localhost:8000/docs`

### Data Persistence
Volumes map host directories to container:
```
./ai-lighting-data/dwg         → /app/data/dwg
./ai-lighting-data/exports     → /app/data/exports
./ai-lighting-data/annotations → /app/data/annotations
./ai-lighting-data/models      → /app/ml/models
```

---

## 📋 Workflow

### 1️⃣ Development & Testing

```bash
# Test build locally (uses port 8001 to avoid conflicts)
./test_docker.sh

# If tests pass, access at:
# http://localhost:8001
```

### 2️⃣ Build & Push to Docker Hub

```bash
# Login to Docker Hub (first time only)
docker login

# Build and push
./build_and_push.sh latest

# Or with versioning
./build_and_push.sh v1.0.0 latest
```

### 3️⃣ Deploy to Server

```bash
# Copy deployment files to server
scp start_server.sh docker-compose.yml user@your-server:~/

# SSH and deploy
ssh user@your-server
./start_server.sh latest
```

### 4️⃣ Access & Monitor

```bash
# Check status
docker ps

# View logs
docker logs -f ai-lighting

# Check health
curl http://localhost:8000/health

# Access frontend
open http://your-server:8000
```

---

## 🎯 Key Features

### ✅ Production Ready
- Multi-stage build (optimized size)
- Health checks configured
- Automatic restart on failure
- Persistent data volumes
- CORS configured (can be restricted)

### ✅ Easy Updates
```bash
# Build new version
./build_and_push.sh v1.1.0 latest

# Deploy on server
./start_server.sh latest
```

### ✅ Self-Contained
- No external dependencies to install on server
- Just need Docker installed
- All Python and Node dependencies bundled
- Frontend pre-built and included

### ✅ Scalable
- Can run multiple instances on different ports
- Works with reverse proxies (Nginx, Caddy)
- Easy to add load balancing

---

## 🔧 Configuration Options

### Change Port
```bash
# Edit docker-compose.yml
ports:
  - "80:8000"  # Use port 80 instead of 8000
```

### Add Environment Variables
```bash
# Create .env file
API_HOST=0.0.0.0
API_PORT=8000

# Use with docker-compose
docker-compose --env-file .env up -d
```

### Resource Limits
```bash
# Add to docker-compose.yml
services:
  ai-lighting:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
```

---

## 📊 Image Details

**Docker Hub:** `turbham/ai-lighting`

**Tags:**
- `latest` - Latest stable production build
- `v1.0.0`, `v1.1.0`, etc. - Specific versions
- `dev` - Development build (with hot-reload)

**Size:** ~800MB - 1.5GB (production)

**Base Images:**
- Frontend builder: `node:18-alpine`
- Runtime: `python:3.11-slim`

**Included:**
- Python 3.11 + all dependencies
- React app (built and optimized)
- FastAPI server
- System dependencies for CAD parsing
- Health check script
- Data directories

---

## 🐛 Troubleshooting

### Build fails?
```bash
# Check Docker is running
docker info

# Check Dockerfile syntax
docker build --no-cache -t test .
```

### Container won't start?
```bash
# Check logs
docker logs ai-lighting

# Common issues:
# - Port already in use: Change port mapping
# - Permission issues: Check volume permissions
# - Missing files: Rebuild image
```

### Frontend not loading?
```bash
# Verify frontend was built
docker exec ai-lighting ls -la /app/ui/dist/

# If empty, rebuild
./build_and_push.sh latest
```

### Push to Docker Hub fails?
```bash
# Login first
docker login

# Check repository name
docker images | grep turbham/ai-lighting
```

---

## 🎓 Learning Resources

**Docker Basics:**
- [Docker Get Started](https://docs.docker.com/get-started/)
- [Docker Compose](https://docs.docker.com/compose/)

**Multi-Stage Builds:**
- [Docker Multi-Stage Docs](https://docs.docker.com/build/building/multi-stage/)

**FastAPI Deployment:**
- [FastAPI in Containers](https://fastapi.tiangolo.com/deployment/docker/)

---

## ✨ Next Steps

### Immediate:
1. ✅ Test locally: `./test_docker.sh`
2. ✅ Build & push: `./build_and_push.sh latest`
3. ✅ Deploy to server: `./start_server.sh latest`

### Optional Enhancements:
- [ ] Set up reverse proxy (Nginx)
- [ ] Configure SSL/HTTPS
- [ ] Add monitoring (Prometheus, Grafana)
- [ ] Set up CI/CD for automatic builds
- [ ] Configure backups for data volumes
- [ ] Add authentication/API keys
- [ ] Restrict CORS for production

---

## 📝 Quick Command Reference

```bash
# BUILD
./build_and_push.sh latest

# DEPLOY
./start_server.sh latest

# MANAGE
docker logs -f ai-lighting
docker restart ai-lighting
docker stop ai-lighting

# UPDATE
./build_and_push.sh latest
./start_server.sh latest

# BACKUP
tar -czf backup.tar.gz ai-lighting-data/
```

---

**Need help?** See [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) for detailed documentation.
