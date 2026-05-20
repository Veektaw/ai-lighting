"""
lighting-ai/services/api/main.py

FastAPI gateway — full pipeline as REST API.

Endpoints:
  GET  /health
  GET  /concepts
  POST /process          Upload plan → run pipeline → return results
  GET  /jobs/{id}        Poll job status
  GET  /exports/{id}/{fmt}   Download dxf | xlsx | pdf | html
  POST /corrections      Submit designer corrections (RL training signal)
"""
from __future__ import annotations
import asyncio, json, traceback, uuid
from pathlib import Path
from typing import Literal, Optional
import sys

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import DWG_DIR, EXPORTS_DIR, CONCEPTS_DIR, MODELS_DIR

app = FastAPI(title="lighting-ai", version="1.0.0",
              description="Automated Rossmann lighting design pipeline")

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# In-memory job store (swap for Redis in production)
JOBS: dict[str, dict] = {}


# ── Pydantic models ───────────────────────────────────────────────────────────

class JobStatus(BaseModel):
    job_id: str
    status: Literal["queued","processing","done","error"]
    message: str = ""
    result: Optional[dict] = None

class CorrectionPayload(BaseModel):
    job_id: str
    corrections: list[dict]


# ── Startup: ensure default concept exists ────────────────────────────────────

def _bootstrap():
    CONCEPTS_DIR.mkdir(parents=True, exist_ok=True)
    default = CONCEPTS_DIR / "rossmann_standard.yaml"
    if not default.exists():
        yaml_src = Path(__file__).parent.parent.parent / "data/concepts/rossmann_standard.yaml"
        if yaml_src.exists():
            import shutil; shutil.copy(yaml_src, default)

_bootstrap()


# ── Pipeline worker ───────────────────────────────────────────────────────────

def _run_pipeline(job_id: str, plan_path: Path,
                  concept_id: str, project_name: str, customer: str):
    try:
        JOBS[job_id]["status"]  = "processing"
        JOBS[job_id]["message"] = "Parsing plan…"

        from services.parser.pdf_parser import RealPlanParser
        from services.classifier.room_classifier_real import RealRoomClassifier
        from services.placer.real_placer import RealLuminairePlacer
        from services.exporter.exporter import export_dwg, export_excel, export_pdf

        # Parse
        parser = RealPlanParser()
        plan = parser.parse(plan_path)

        JOBS[job_id]["message"] = "Classifying zones…"
        classified = RealRoomClassifier().classify(plan)

        JOBS[job_id]["message"] = "Placing luminaires…"
        result = RealLuminairePlacer().place_all(plan, classified)

        JOBS[job_id]["message"] = "Exporting…"
        stem = f"{job_id}_{plan_path.stem}"
        pfx  = str(EXPORTS_DIR / stem)

        dwg_out  = export_dwg(result, classified,
                              source_dxf_path=str(plan_path) if plan_path.suffix=='.dxf' else None,
                              output_path=pfx+"_luminaires.dxf")
        xlsx_out = export_excel(result, classified,
                                project_name=project_name, customer=customer,
                                concept_id=concept_id,
                                output_path=pfx+"_schedule.xlsx")
        pdf_out  = export_pdf(result, classified,
                              concept_id=concept_id, customer=customer,
                              project_name=project_name,
                              output_path=pfx+"_documentation")

        placed_data = [
            {"id":i,"x":round(lp.x),"y":round(lp.y),"rotation":lp.rotation,
             "zone_type":lp.zone_type,"lumi_type":lp.lumi_type,
             "product_code":lp.product_code,"description":lp.description,
             "wattage":lp.wattage,"lux_output":lp.lux_output,
             "mounting_type":lp.mounting_type,"beam_angle_deg":lp.beam_angle_deg,
             "grid_snapped":lp.grid_snapped,"shelf_aligned":lp.shelf_aligned}
            for i,lp in enumerate(result.placed)
        ]
        zones_data = [
            {"index":z.polygon_index,"zone_type":z.zone_type,
             "confidence":round(z.confidence,3),"method":z.method,
             "area_m2":round(z.area_m2,2),"bounds":list(z.polygon.bounds)}
            for z in classified.zones
        ]

        JOBS[job_id].update({
            "status": "done",
            "message": "Pipeline complete",
            "result": {
                "summary":          result.summary(),
                "total_luminaires": len(result.placed),
                "total_wattage":    round(result.total_wattage()),
                "type_A":           len(result.by_type("A")),
                "type_B":           len(result.by_type("B")),
                "zones":            zones_data,
                "placed":           placed_data,
                "exports": {
                    "dxf":  str(dwg_out),
                    "xlsx": str(xlsx_out),
                    "pdf":  str(pdf_out),
                },
            },
        })

    except ValueError as e:
        msg = str(e)
        JOBS[job_id]["status"]  = "error"
        JOBS[job_id]["message"] = msg
        print(f"[Job {job_id}] ValueError: {msg}")

    except ImportError as e:
        msg = (
            "Missing dependency — PyMuPDF not installed correctly. "
            "Fix: pip uninstall fitz && pip install pymupdf"
        )
        JOBS[job_id]["status"]  = "error"
        JOBS[job_id]["message"] = msg
        print(f"[Job {job_id}] ImportError: {e}")

    except Exception as e:
        tb  = traceback.format_exc()
        msg = f"{type(e).__name__}: {e}"
        JOBS[job_id]["status"]    = "error"
        JOBS[job_id]["message"]   = msg
        JOBS[job_id]["traceback"] = tb
        print(f"[Job {job_id}] Unhandled exception:\n{tb}")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status":"ok","version":"1.0.0"}


@app.get("/concepts")
def get_concepts():
    yamls = list(CONCEPTS_DIR.glob("*.yaml"))
    return {"concepts": [p.stem for p in yamls] or ["rossmann_standard"]}


@app.post("/process", response_model=JobStatus)
async def process(
    background_tasks: BackgroundTasks,
    file:         UploadFile = File(...),
    concept_id:   str        = Form("rossmann_standard"),
    project_name: str        = Form("Lighting Project"),
    customer:     str        = Form("Dirk Rossmann GmbH"),
):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".dxf",".dwg",".pdf"):
        raise HTTPException(400, "Only .pdf, .dxf and .dwg files accepted.")

    job_id   = str(uuid.uuid4())[:8]
    savepath = DWG_DIR / f"{job_id}_{file.filename}"
    savepath.write_bytes(await file.read())

    JOBS[job_id] = {"status":"queued","message":"Job queued","result":None}
    background_tasks.add_task(
        _run_pipeline, job_id, savepath, concept_id, project_name, customer)

    return JobStatus(job_id=job_id, status="queued",
                     message="Queued — poll /jobs/"+job_id)


@app.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "Job not found")
    j = JOBS[job_id]
    return JobStatus(job_id=job_id, status=j["status"],
                     message=j["message"], result=j.get("result"))


@app.get("/exports/{job_id}/{fmt}")
def download_export(job_id: str,
                    fmt: Literal["dxf","xlsx","pdf","html"]):
    if job_id not in JOBS:
        raise HTTPException(404, "Job not found")
    j = JOBS[job_id]
    if j["status"] != "done":
        raise HTTPException(400, f"Job status is '{j['status']}', not done.")

    exports = j["result"]["exports"]
    path_map = {"dxf": exports["dxf"], "xlsx": exports["xlsx"],
                "pdf": exports["pdf"], "html": exports["pdf"]}
    path = Path(path_map[fmt])
    if not path.exists():
        raise HTTPException(404, f"Export file not found: {path.name}")
    return FileResponse(str(path), filename=path.name)


@app.post("/corrections")
def submit_corrections(payload: CorrectionPayload):
    if payload.job_id not in JOBS:
        raise HTTPException(404, "Job not found")
    JOBS[payload.job_id].setdefault("corrections", []).extend(payload.corrections)
    # Persist for RL training
    out = EXPORTS_DIR / f"{payload.job_id}_corrections.json"
    existing = json.loads(out.read_text()) if out.exists() else []
    existing.extend(payload.corrections)
    out.write_text(json.dumps(existing, indent=2))
    return {"status":"recorded","count":len(payload.corrections),
            "message":"Saved for RL training"}


# ── Dev server ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    from config import API_HOST, API_PORT
    uvicorn.run("services.api.main:app", host=API_HOST,
                port=API_PORT, reload=True)