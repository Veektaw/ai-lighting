"""
lighting-ai/setup.py  — install all dependencies and verify the environment.
Run once: python setup.py
"""
import subprocess, sys

PACKAGES = [
    "pymupdf", "ezdxf", "shapely", "numpy", "scipy", "networkx",
    "scikit-learn", "xgboost", "fastapi", "uvicorn[standard]",
    "pyyaml", "openpyxl", "jinja2", "pillow", "httpx",
    "python-multipart", "aiofiles",
]

CHECKS = [
    ("fitz (PyMuPDF)", "import fitz"),
    ("ezdxf",          "import ezdxf"),
    ("shapely",        "from shapely.geometry import Polygon"),
    ("numpy",          "import numpy as np"),
    ("scikit-learn",   "from sklearn.ensemble import RandomForestClassifier"),
    ("fastapi",        "from fastapi import FastAPI"),
    ("openpyxl",       "import openpyxl"),
    ("jinja2",         "from jinja2 import Template"),
    ("yaml",           "import yaml"),
]

def install():
    print("Installing lighting-ai dependencies …")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--break-system-packages", "-q"] + PACKAGES
    )
    print("Installation complete.\n")

def verify():
    print("Verifying imports …")
    ok = True
    for name, stmt in CHECKS:
        try:
            exec(stmt)
            print(f"  ✓  {name}")
        except ImportError as e:
            print(f"  ✗  {name}: {e}")
            ok = False
    return ok

if __name__ == "__main__":
    install()
    if verify():
        print("\n✓  All checks passed. Run: python main.py pipeline --demo")
    else:
        print("\n✗  Some imports failed — check the errors above.")
        sys.exit(1)