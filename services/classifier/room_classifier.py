"""
lighting-ai/services/classifier/room_classifier.py

Layer 2 — Room Classification (M2)

Classifies each room polygon into a zone type using:
  1. Rule engine   (covers ~70 % of cases, deterministic)
  2. ML classifier (scikit-learn RandomForest, covers ambiguous cases)
  3. Graph context (NetworkX adjacency boost)

Outputs a ZoneResult per polygon.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import sys

import networkx as nx
import numpy as np
from shapely.geometry import Polygon, Point

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import ZONE_TYPES, MODELS_DIR
from services.parser.dwg_parser import ParsedPlan, FurnitureInsert


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ZoneResult:
    polygon_index: int
    polygon: Polygon
    zone_type: str
    confidence: float          # 0–1
    method: str                # "rule" | "ml" | "graph_boosted"
    furniture_counts: dict     = field(default_factory=dict)
    area_m2: float             = 0.0
    ceiling_height_mm: float   = 3000.0


@dataclass
class ClassifiedPlan:
    source_file: str
    zones: list[ZoneResult]

    def by_type(self, zone_type: str) -> list[ZoneResult]:
        return [z for z in self.zones if z.zone_type == zone_type]

    def summary(self) -> str:
        from collections import Counter
        counts = Counter(z.zone_type for z in self.zones)
        return f"ClassifiedPlan: {dict(counts)}"


# ─────────────────────────────────────────────────────────────────────────────
# Feature extraction
# ─────────────────────────────────────────────────────────────────────────────

FURNITURE_TYPES = ["checkout", "shelving", "desk", "storage", "door",
                   "window", "unknown"]


def extract_features(polygon: Polygon,
                     furniture_in_zone: list[FurnitureInsert],
                     ceiling_h: float = 3000.0) -> dict:
    """Return a feature dict for ML and rule evaluation."""
    area = polygon.area / 1e6         # m²
    bounds = polygon.bounds
    width  = (bounds[2] - bounds[0]) / 1000   # m
    height = (bounds[3] - bounds[1]) / 1000   # m
    aspect = max(width, height) / max(min(width, height), 0.1)

    counts = {ftype: 0 for ftype in FURNITURE_TYPES}
    for fi in furniture_in_zone:
        ftype = fi.inferred_type
        if ftype in counts:
            counts[ftype] += 1

    total_furn = sum(counts.values())

    return {
        "area_m2":          area,
        "width_m":          width,
        "height_m":         height,
        "aspect_ratio":     aspect,
        "perimeter_m":      polygon.length / 1000,
        "ceiling_h_m":      ceiling_h / 1000,
        "n_checkout":       counts["checkout"],
        "n_shelving":       counts["shelving"],
        "n_desk":           counts["desk"],
        "n_storage":        counts["storage"],
        "n_door":           counts["door"],
        "n_window":         counts["window"],
        "n_unknown":        counts["unknown"],
        "total_furniture":  total_furn,
        "shelving_density": counts["shelving"] / max(area, 0.1),
        **counts,
    }


def features_to_vector(feat: dict) -> np.ndarray:
    keys = [
        "area_m2", "width_m", "height_m", "aspect_ratio", "perimeter_m",
        "ceiling_h_m", "n_checkout", "n_shelving", "n_desk", "n_storage",
        "n_door", "n_window", "total_furniture", "shelving_density",
    ]
    return np.array([feat[k] for k in keys], dtype=np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# Rule engine
# ─────────────────────────────────────────────────────────────────────────────

def rule_classify(feat: dict) -> tuple[str, float]:
    """
    Deterministic rule classification.
    Returns (zone_type, confidence) or ("unknown", 0.0) to defer to ML.
    """
    n_checkout  = feat["n_checkout"]
    n_shelving  = feat["n_shelving"]
    area        = feat["area_m2"]
    aspect      = feat["aspect_ratio"]
    n_desk      = feat["n_desk"]
    n_storage   = feat["n_storage"]

    # ── Checkout zone ──────────────────────────────────────────────────────
    if n_checkout >= 1 and area < 80:
        return "checkout_zone", 0.95

    # ── Sales floor (shelving dominant, large area) ────────────────────────
    if n_shelving >= 3 and area >= 50:
        return "sales_floor", 0.90
    if n_shelving >= 1 and area >= 150:
        return "sales_floor", 0.80

    # ── Storage (small, low furniture variety) ─────────────────────────────
    if n_storage >= 1 and area < 40 and n_shelving == 0:
        return "storage", 0.85
    if area < 15 and feat["total_furniture"] == 0:
        return "storage", 0.70

    # ── Office / desk area ─────────────────────────────────────────────────
    if n_desk >= 2 and n_shelving == 0:
        return "office", 0.85

    # ── Corridor (very elongated, no furniture) ────────────────────────────
    if aspect > 4 and feat["total_furniture"] == 0 and area < 30:
        return "corridor", 0.80

    # ── Entrance (large, near exterior — approximated by low furniture) ────
    if area >= 20 and feat["total_furniture"] == 0 and aspect < 2.5:
        return "entrance", 0.60   # low confidence → ML may override

    return "unknown", 0.0


# ─────────────────────────────────────────────────────────────────────────────
# ML classifier wrapper
# ─────────────────────────────────────────────────────────────────────────────

class MLClassifier:
    """Thin wrapper around a persisted scikit-learn model."""

    MODEL_PATH = MODELS_DIR / "room_classifier.pkl"

    def __init__(self):
        self._model = None
        self._load()

    def _load(self):
        if self.MODEL_PATH.exists():
            import pickle
            with open(self.MODEL_PATH, "rb") as f:
                self._model = pickle.load(f)

    def predict(self, feat_vec: np.ndarray) -> tuple[str, float]:
        if self._model is None:
            return "unknown", 0.0
        probs = self._model.predict_proba(feat_vec.reshape(1, -1))[0]
        idx   = int(np.argmax(probs))
        return self._model.classes_[idx], float(probs[idx])

    def is_available(self) -> bool:
        return self._model is not None

    def train(self, X: np.ndarray, y: list[str]):
        """Train from a numpy feature matrix and label list."""
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import LabelEncoder
        import pickle

        clf = RandomForestClassifier(
            n_estimators=200,
            max_depth=12,
            min_samples_leaf=2,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        clf.fit(X, y)
        self._model = clf
        self.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(self.MODEL_PATH, "wb") as f:
            pickle.dump(clf, f)
        print(f"Classifier saved → {self.MODEL_PATH}")


# ─────────────────────────────────────────────────────────────────────────────
# Graph context
# ─────────────────────────────────────────────────────────────────────────────

def build_adjacency_graph(zones: list[ZoneResult]) -> nx.Graph:
    """
    Build a room adjacency graph.
    Two zones are adjacent if their polygons share an edge (buffer 200 mm).
    """
    G = nx.Graph()
    for z in zones:
        G.add_node(z.polygon_index, zone_type=z.zone_type,
                   confidence=z.confidence)

    for i, za in enumerate(zones):
        for j, zb in enumerate(zones):
            if j <= i:
                continue
            if za.polygon.buffer(200).intersects(zb.polygon.buffer(200)):
                G.add_edge(za.polygon_index, zb.polygon_index)
    return G


def graph_boost(zones: list[ZoneResult], G: nx.Graph) -> list[ZoneResult]:
    """
    Apply simple adjacency rules to improve low-confidence classifications.

    Rules:
      - Unknown zone adjacent to checkout_zone + sales_floor → entrance
      - Unknown zone adjacent only to office → office (break room / meeting)
    """
    for zone in zones:
        if zone.confidence >= 0.75:
            continue   # already confident, skip

        neighbors = list(G.neighbors(zone.polygon_index))
        nb_types  = {G.nodes[n]["zone_type"] for n in neighbors}

        if "checkout_zone" in nb_types and "sales_floor" in nb_types:
            if zone.zone_type in ("unknown", "entrance"):
                zone.zone_type  = "entrance"
                zone.confidence = 0.72
                zone.method     = "graph_boosted"

        elif nb_types == {"office"}:
            if zone.zone_type == "unknown":
                zone.zone_type  = "office"
                zone.confidence = 0.65
                zone.method     = "graph_boosted"

    return zones


# ─────────────────────────────────────────────────────────────────────────────
# Main classifier
# ─────────────────────────────────────────────────────────────────────────────

class RoomClassifier:
    def __init__(self):
        self.ml = MLClassifier()

    def classify(self, plan: ParsedPlan) -> ClassifiedPlan:
        zones: list[ZoneResult] = []

        for idx, poly in enumerate(plan.room_polygons):
            # Furniture contained in this polygon
            furniture_in = [
                fi for fi in plan.furniture
                if poly.contains(Point(fi.position))
            ]

            feat = extract_features(poly, furniture_in,
                                    plan.ceiling_height_mm)

            # 1. Rule engine
            zone_type, confidence = rule_classify(feat)

            if confidence >= 0.75:
                method = "rule"
            else:
                # 2. ML fallback
                if self.ml.is_available():
                    ml_type, ml_conf = self.ml.predict(
                        features_to_vector(feat))
                    if ml_conf > confidence:
                        zone_type  = ml_type
                        confidence = ml_conf
                        method     = "ml"
                    else:
                        method = "rule"
                else:
                    # No ML model trained yet — stay with rule result
                    method = "rule"
                    if zone_type == "unknown":
                        # Last resort: largest zones are sales_floor
                        if feat["area_m2"] > 100:
                            zone_type  = "sales_floor"
                            confidence = 0.50
                        else:
                            zone_type  = "storage"
                            confidence = 0.40

            zones.append(ZoneResult(
                polygon_index=idx,
                polygon=poly,
                zone_type=zone_type,
                confidence=confidence,
                method=method,
                furniture_counts={ft: feat[f"n_{ft}"]
                                  for ft in ["checkout", "shelving",
                                             "desk", "storage"]},
                area_m2=feat["area_m2"],
                ceiling_height_mm=plan.ceiling_height_mm,
            ))

        # 3. Graph boost
        G = build_adjacency_graph(zones)
        zones = graph_boost(zones, G)

        return ClassifiedPlan(source_file=plan.source_file, zones=zones)


# ─────────────────────────────────────────────────────────────────────────────
# CLI smoke test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from services.parser.dwg_parser import DWGParser

    # Generate synthetic plan
    parser = DWGParser()
    plan   = parser.parse("/tmp/test_plan.dxf"
                          if os.path.exists("/tmp/test_plan.dxf")
                          else "")
    if not plan.room_polygons:
        # Inject synthetic polygon
        from shapely.geometry import box
        plan.room_polygons = [
            box(0, 0, 10000, 8000),    # large sales area
            box(10000, 0, 12000, 3000), # small checkout
        ]
        from services.parser.dwg_parser import FurnitureInsert
        plan.furniture = [
            FurnitureInsert("SHELF_1200", (2000,2000), 0, "FURNITURE",
                            "shelving"),
            FurnitureInsert("SHELF_1200", (4000,2000), 0, "FURNITURE",
                            "shelving"),
            FurnitureInsert("SHELF_1200", (6000,2000), 0, "FURNITURE",
                            "shelving"),
            FurnitureInsert("POS_DESK",  (11000,1500),0, "CHECKOUT",
                            "checkout"),
        ]

    clf    = RoomClassifier()
    result = clf.classify(plan)
    print(result.summary())
    for z in result.zones:
        print(f"  Zone {z.polygon_index}: {z.zone_type} "
              f"(conf={z.confidence:.2f}, method={z.method}, "
              f"area={z.area_m2:.1f}m²)")