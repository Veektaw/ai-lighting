"""
lighting-ai/services/parser/dwg_parser.py

Layer 1 — DWG Import & Parsing (M1)

Reads a DXF/DWG file and extracts:
  - Room boundary polygons (from closed polylines)
  - Furniture block inserts (name, position, rotation)
  - Ceiling grid lines
  - Doors, windows, annotations

All geometry is returned in model-space millimetres.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import ezdxf
import numpy as np
from shapely.geometry import Polygon, LineString, MultiPolygon, Point
from shapely.ops import unary_union

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import DEFAULT_LAYER_MAP


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FurnitureInsert:
    block_name: str
    position: tuple[float, float]   # (x, y) in mm
    rotation: float                 # degrees
    layer: str
    inferred_type: str = "unknown"  # set by block_name_to_type()


@dataclass
class CeilingGridLine:
    start: tuple[float, float]
    end:   tuple[float, float]
    layer: str


@dataclass
class ParsedPlan:
    source_file: str
    room_polygons: list[Polygon]            = field(default_factory=list)
    furniture: list[FurnitureInsert]        = field(default_factory=list)
    grid_lines: list[CeilingGridLine]       = field(default_factory=list)
    door_positions: list[tuple]             = field(default_factory=list)
    window_positions: list[tuple]           = field(default_factory=list)
    annotations: list[dict]                 = field(default_factory=list)
    ceiling_height_mm: float                = 3000.0
    layer_map: dict                         = field(default_factory=dict)
    bounds: Optional[tuple]                 = None  # (minx, miny, maxx, maxy)

    def summary(self) -> str:
        return (
            f"ParsedPlan({Path(self.source_file).name}): "
            f"{len(self.room_polygons)} rooms, "
            f"{len(self.furniture)} furniture items, "
            f"{len(self.grid_lines)} grid lines"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Block name → furniture type mapping
# ─────────────────────────────────────────────────────────────────────────────

BLOCK_TYPE_MAP: dict[str, str] = {
    # Checkout / POS
    "checkout": "checkout", "pos": "checkout", "cashier": "checkout",
    "kasse": "checkout",
    # Shelving / racks
    "shelf": "shelving", "shelving": "shelving", "rack": "shelving",
    "gondola": "shelving", "regal": "shelving",
    # Service / office
    "desk": "desk", "counter": "desk", "service": "desk",
    "theke": "desk",
    # Doors / windows (block-style)
    "door": "door", "tur": "door",
    "window": "window", "fenster": "window",
    # Storage
    "storage": "storage", "pallet": "storage", "euro": "storage",
}


def block_name_to_type(block_name: str) -> str:
    name_lower = block_name.lower()
    for key, ftype in BLOCK_TYPE_MAP.items():
        if key in name_lower:
            return ftype
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Layer helpers
# ─────────────────────────────────────────────────────────────────────────────

def build_layer_set(layer_map: dict) -> dict[str, set[str]]:
    """Return {category: {layer_name_upper, ...}} for fast membership tests."""
    return {
        cat: {l.upper() for l in layers}
        for cat, layers in layer_map.items()
    }


def entity_category(entity, layer_sets: dict[str, set[str]]) -> str:
    layer = entity.dxf.layer.upper()
    for cat, names in layer_sets.items():
        if layer in names:
            return cat
        # prefix match: layer "A-WALL-DEMO" still matches "A-WALL"
        for name in names:
            if layer.startswith(name):
                return cat
    return "other"


# ─────────────────────────────────────────────────────────────────────────────
# Polyline → Shapely polygon
# ─────────────────────────────────────────────────────────────────────────────

def lwpolyline_to_polygon(entity) -> Optional[Polygon]:
    """Convert a LWPOLYLINE to a Shapely Polygon if it is closed."""
    try:
        pts = [(p[0], p[1]) for p in entity.get_points()]
        if len(pts) < 3:
            return None
        is_closed = entity.closed or (pts[0] == pts[-1])
        if not is_closed:
            # Auto-close if start/end are within 1 mm
            if math.dist(pts[0], pts[-1]) < 1.0:
                is_closed = True
        if not is_closed:
            return None
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly if poly.area > 100 else None   # ignore < 100 mm² noise
    except Exception:
        return None


def lines_to_polygons(lines: list) -> list[Polygon]:
    """
    Attempt to close open line-segment loops into polygons.
    Used when room boundaries are drawn as individual LINE entities
    rather than closed LWPOLYLINE.
    """
    from shapely.ops import polygonize
    geoms = [LineString([l.dxf.start[:2], l.dxf.end[:2]]) for l in lines]
    polys = list(polygonize(geoms))
    return [p for p in polys if p.area > 10_000]  # > 0.01 m²


# ─────────────────────────────────────────────────────────────────────────────
# Main parser
# ─────────────────────────────────────────────────────────────────────────────

class DWGParser:
    def __init__(self, layer_map: dict = None):
        self.layer_map = layer_map or DEFAULT_LAYER_MAP
        self._layer_sets = build_layer_set(self.layer_map)

    # ── Public API ────────────────────────────────────────────────────────────

    def parse(self, filepath: str | Path) -> ParsedPlan:
        """
        Parse a DXF/DWG file and return a ParsedPlan.

        Supports:
          - DXF R12 through R2018+
          - DWG (ezdxf recovers most DWG via ODA file converter path;
            for pure DWG supply a pre-converted DXF)
        """
        filepath = Path(filepath)
        plan = ParsedPlan(
            source_file=str(filepath),
            layer_map=self.layer_map,
        )

        try:
            doc = ezdxf.readfile(str(filepath))
        except ezdxf.DXFStructureError:
            # Try recovery mode for damaged files
            doc, _ = ezdxf.recover.readfile(str(filepath))

        msp = doc.modelspace()

        wall_lines: list = []
        raw_polys: list[Polygon] = []

        for entity in msp:
            etype = entity.dxftype()
            cat   = entity_category(entity, self._layer_sets)

            # ── Closed polylines → room boundaries ────────────────────────
            if etype == "LWPOLYLINE":
                poly = lwpolyline_to_polygon(entity)
                if poly:
                    if cat in ("walls", "other", "ceiling"):
                        raw_polys.append(poly)
                    elif cat == "grid":
                        pass  # handled as grid lines below

            elif etype == "POLYLINE":
                pts = [(v.dxf.location.x, v.dxf.location.y)
                       for v in entity.vertices]
                if len(pts) >= 3:
                    try:
                        poly = Polygon(pts)
                        if poly.is_valid and poly.area > 100:
                            raw_polys.append(poly)
                    except Exception:
                        pass

            # ── Individual lines → collect for polygonisation ─────────────
            elif etype == "LINE":
                if cat in ("walls", "other"):
                    wall_lines.append(entity)
                elif cat in ("grid", "ceiling"):
                    plan.grid_lines.append(CeilingGridLine(
                        start=(entity.dxf.start.x, entity.dxf.start.y),
                        end=(entity.dxf.end.x, entity.dxf.end.y),
                        layer=entity.dxf.layer,
                    ))

            # ── Block inserts → furniture ──────────────────────────────────
            elif etype == "INSERT":
                bname = entity.dxf.name
                pos   = (entity.dxf.insert.x, entity.dxf.insert.y)
                rot   = getattr(entity.dxf, "rotation", 0.0)
                fi    = FurnitureInsert(
                    block_name=bname,
                    position=pos,
                    rotation=rot,
                    layer=entity.dxf.layer,
                    inferred_type=block_name_to_type(bname),
                )
                plan.furniture.append(fi)

            # ── Text/Mtext → annotations ───────────────────────────────────
            elif etype in ("TEXT", "MTEXT"):
                text = (entity.dxf.text if etype == "TEXT"
                        else entity.plain_mtext())
                pos  = (entity.dxf.insert.x, entity.dxf.insert.y)
                plan.annotations.append({"text": text, "position": pos,
                                          "layer": entity.dxf.layer})

        # ── Polygonise loose wall lines ────────────────────────────────────
        if wall_lines:
            raw_polys.extend(lines_to_polygons(wall_lines))

        # ── Deduplicate & filter room polygons ─────────────────────────────
        plan.room_polygons = self._clean_polygons(raw_polys)

        # ── Bounding box ───────────────────────────────────────────────────
        if plan.room_polygons:
            all_geom = unary_union(plan.room_polygons)
            plan.bounds = all_geom.bounds

        return plan

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _clean_polygons(raw: list[Polygon]) -> list[Polygon]:
        """
        Remove duplicates, nested small polygons, and invalid geometry.
        Keeps the largest enclosing polygon when one fully contains another.
        """
        valid = [p for p in raw if p.is_valid and p.area > 1_000]
        valid.sort(key=lambda p: p.area, reverse=True)

        kept: list[Polygon] = []
        for poly in valid:
            dominated = False
            for big in kept:
                if big.contains(poly) and big.area / poly.area > 0.95:
                    dominated = True
                    break
            if not dominated:
                kept.append(poly)
        return kept


# ─────────────────────────────────────────────────────────────────────────────
# CLI smoke test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        # Create a synthetic test DXF if no file is provided
        print("No file given — running synthetic test...")
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()

        # Draw a simple rectangular room (10m × 8m)
        room_pts = [(0,0),(10000,0),(10000,8000),(0,8000),(0,0)]
        msp.add_lwpolyline(room_pts, close=True,
                           dxfattribs={"layer": "WALLS"})

        # Add a shelf block reference
        msp.add_blockref("SHELF_1200",
                         insert=(2000, 2000),
                         dxfattribs={"layer": "FURNITURE"})

        # Add ceiling grid lines
        for x in range(0, 10001, 600):
            msp.add_line((x, 0), (x, 8000),
                         dxfattribs={"layer": "CEILING-GRID"})
        for y in range(0, 8001, 600):
            msp.add_line((0, y), (10000, y),
                         dxfattribs={"layer": "CEILING-GRID"})

        test_path = "/tmp/test_plan.dxf"
        doc.saveas(test_path)
        filepath = test_path
    else:
        filepath = sys.argv[1]

    parser = DWGParser()
    plan   = parser.parse(filepath)
    print(plan.summary())
    print(f"  Bounds: {plan.bounds}")
    for i, poly in enumerate(plan.room_polygons):
        print(f"  Room {i}: area={poly.area/1e6:.2f} m²")
    for fi in plan.furniture[:5]:
        print(f"  Furniture: {fi.block_name} → {fi.inferred_type} @ {fi.position}")
    print(f"  Grid lines: {len(plan.grid_lines)}")