# ai-lighting-project

Automated lighting design pipeline for Rossmann retail stores.

**Validated accuracy vs real plan (VKST 3600 Hamburg Jungfernstieg EG):**
| Metric | Pipeline | Real plan | Accuracy |
|--------|----------|-----------|----------|
| Total luminaires | 168 | 167 | 99.4% |
| Type A (15W 40°) | 107 | 106 | 99.1% |
| Type B (20W 60°) | 61 | 61 | **100.0%** |

---

## Quick start (Backend)

```bash
# 1. Install dependencies
python setup.py

# 2. Use the uploaded Rossmann demo plan
python main.py pipeline --demo

# 3. Start API server  (then open http://localhost:3000 for UI)
python main.py api
```

## Quick start (Frontend) another terminal

```bash
# 1. 
cd ui

# 2. 
npm install

# 3. Start app
npm run dev
```

## 🐳 Docker Deployment (Production)

**Deploy to your own server in 3 steps:**

```bash
# 1. Build and push to Docker Hub
./build_and_push.sh latest

# 2. On your server, pull and run
./start_server.sh latest

# 3. Access at http://your-server:8000
```

**Or use Docker Compose:**
```bash
docker-compose up -d
```

📚 **Full documentation:** See [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) and [DOCKER_QUICK_REF.md](DOCKER_QUICK_REF.md)

🐋 **Docker Hub:** `turbham/ai-lighting`

---

## Project structure

```
lighting-ai/
├── main.py                         # Master CLI entry point
├── config.py                       # Central configuration
├── requirements.txt
├── setup.py                        # Dependency installer
│
├── services/
│   ├── parser/
│   │   └── pdf_parser.py           # PDF/DXF floor plan parser
│   ├── classifier/
│   │   └── room_classifier_real.py # Zone classifier (label-driven + ML)
│   ├── placer/
│   │   └── real_placer.py          # Luminaire placement (99.4% accurate)
│   ├── exporter/
│   │   └── exporter.py             # DXF + Excel BOM + PDF/HTML docs
│   └── api/
│       └── main.py                 # FastAPI REST gateway
│
├── ml/
│   ├── models/                     # Trained model artefacts (.pkl)
│   └── training/
│       └── train_classifier.py     # Classifier training + RL loop
│
├── data/
│   ├── concepts/
│   │   └── rossmann_standard.yaml  # Concept model (product specs + rules)
│   ├── annotations/
│   │   ├── calibration_rossmann_eg.json  # Grid calibration from real plan
│   │   └── labels.jsonl            # Training labels (auto-generated)
│   ├── exports/                    # Generated DXF / Excel / HTML outputs
│   └── dwg/                        # Uploaded plan files
│
├── ui/                             # React frontend (Vite)
│   └── src/App.jsx
└── infra/
    ├── docker-compose.yml
    └── Dockerfile.api
```

---

## CLI reference

### `pipeline` — run on a real file
```bash
python main.py pipeline --file plan.pdf
python main.py pipeline --file plan.dwg --pdf-fallback plan.pdf
python main.py pipeline --demo                     # uses uploaded Rossmann plans
python main.py pipeline --file plan.pdf \
    --concept rossmann_standard \
    --project-name "Hamburg EG" \
    --customer "Dirk Rossmann GmbH"
```

### `validate` — check accuracy vs ground-truth output plan
```bash
python main.py validate
```

### `train` — retrain the zone classifier
```bash
python main.py train --synthetic                   # bootstrap 
python main.py train --from-reference --synthetic  # real plan + synthetic
python main.py train --annotations data/annotations/labels.jsonl
python main.py train --corrections data/exports/  
```

### `api` — start the REST server
```bash
python main.py api
# → http://localhost:8000/docs  (Swagger UI)
```

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check |
| `GET`  | `/concepts` | List concept models |
| `POST` | `/process` | Upload plan → run pipeline |
| `GET`  | `/jobs/{id}` | Poll job status |
| `GET`  | `/exports/{id}/{fmt}` | Download `dxf`\|`xlsx`\|`pdf` |
| `POST` | `/corrections` | Submit designer corrections (RL) |

---

## Input formats

| Format | Support | Notes |
|--------|---------|-------|
| `.pdf` | ✅ Native | Scale auto-detected (1:50, 1:75, 1:100…) |
| `.dxf` | ✅ Native | ASCII DXF via ezdxf |
| `.dwg` | ⚠️ Via PDF | Binary DWG needs companion PDF or [ODA converter](https://www.opendesign.com/guestfiles/oda_file_converter) |

---

## Concept model (YAML)

Add new customers by creating `data/concepts/{concept_id}.yaml`.
The YAML specifies luminaires per zone, lux targets, grid pitch, and mounting rules.
See `data/concepts/rossmann_standard.yaml` for the full schema.

---

## RL correction loop

Designer corrections submitted via `POST /corrections` are saved to
`data/exports/{job_id}_corrections.json`. Run periodically:

```bash
python main.py train --corrections data/exports/
```

---

## Placement algorithm

1. Parse PDF → extract shelf height labels (`57`, `47`, `77`, `57/47`…)
2. Filter labels to the calibrated sales-floor convex hull (from reference plan)
3. Snap each label to the nearest **1250mm grid intersection**
4. Deduplicate — one luminaire per grid node
5. Classify: nodes inside the eroded hull (−1600mm) → **Type A** (15W 40°);
   outer ring → **Type B** (20W 60°)
6. Export DXF (luminaires as INSERT blocks), Excel BOM, PDF/HTML docs

<!-- ---

## Docker

```bash
cd infra
docker-compose up          # starts API :8000 + UI :3000
```

--- -->

## Open-source dependencies

| Library | Purpose |
|---------|---------|
| `pymupdf` | PDF vector path extraction |
| `ezdxf` | DXF read/write |
| `shapely` | Polygon geometry |
| `scikit-learn` | Zone classifier (RandomForest) |
| `fastapi` | REST API |
| `openpyxl` | Excel BOM |
| `jinja2` | PDF/HTML templates |
| `numpy` | Numerical operations |