"""
lighting-ai/services/placer/luminaire_placer.py

Layer 5 — Automated Luminaire Placement (M4)

Two-stage placement:
  Stage A: Grid-snapped constraint solver (deterministic)
  Stage B: Shelf-alignment override for sales_floor zones

Output: PlacementResult with (x, y, luminaire_spec) per placed unit.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import sys

import numpy as np
from shapely.geometry import Polygon, Point, MultiPoint, LineString, box
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import GRID_PITCH_MM, MIN_WALL_CLEARANCE, MIN_LUMI_SPACING
from services.classifier.room_classifier import ZoneResult
from services.classifier.luminaire_selector import (
    LuminaireSpec, SelectionResult, ZoneConfig
)
from services.parser.dwg_parser import ParsedPlan, FurnitureInsert, CeilingGridLine


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PlacedLuminaire:
    x: float                    # model-space mm
    y: float                    # model-space mm
    luminaire: LuminaireSpec
    zone_type: str
    mounting_type: str
    rotation: float = 0.0       # degrees
    is_snapped_to_grid: bool = False
    aligned_to_shelf: bool  = False


@dataclass
class PlacementResult:
    source_file: str
    placed: list[PlacedLuminaire] = field(default_factory=list)
    corrections: list[dict]       = field(default_factory=list)  # RL training

    def total_wattage(self) -> float:
        return sum(p.luminaire.wattage for p in self.placed)

    def by_zone(self, zone_type: str) -> list[PlacedLuminaire]:
        return [p for p in self.placed if p.zone_type == zone_type]

    def summary(self) -> str:
        from collections import Counter
        counts = Counter(p.zone_type for p in self.placed)
        return (f"PlacementResult: {len(self.placed)} luminaires, "
                f"{self.total_wattage():.0f}W total | {dict(counts)}")


# ─────────────────────────────────────────────────────────────────────────────
# Grid helpers
# ─────────────────────────────────────────────────────────────────────────────

def detect_grid_pitch(grid_lines: list[CeilingGridLine],
                      fallback: float = GRID_PITCH_MM) -> tuple[float, float]:
    """
    Estimate grid pitch in X and Y from ceiling grid lines.
    Returns (pitch_x_mm, pitch_y_mm).
    """
    h_gaps, v_gaps = [], []

    h_lines = sorted(
        [l for l in grid_lines if abs(
            (l.end[1] - l.start[1])) < abs((l.end[0] - l.start[0]))],
        key=lambda l: l.start[1]
    )
    v_lines = sorted(
        [l for l in grid_lines if abs(
            (l.end[0] - l.start[0])) < abs((l.end[1] - l.start[1]))],
        key=lambda l: l.start[0]
    )

    for i in range(1, len(h_lines)):
        gap = abs(h_lines[i].start[1] - h_lines[i-1].start[1])
        if 200 < gap < 2000:
            h_gaps.append(gap)
    for i in range(1, len(v_lines)):
        gap = abs(v_lines[i].start[0] - v_lines[i-1].start[0])
        if 200 < gap < 2000:
            v_gaps.append(gap)

    pitch_x = float(np.median(v_gaps)) if v_gaps else fallback
    pitch_y = float(np.median(h_gaps)) if h_gaps else fallback
    return pitch_x, pitch_y


def generate_grid_candidates(polygon: Polygon,
                              pitch_x: float,
                              pitch_y: float,
                              clearance: float = MIN_WALL_CLEARANCE
                              ) -> list[tuple[float, float]]:
    """
    Generate all grid intersection points inside the polygon
    with the required wall clearance.
    """
    bounds  = polygon.bounds
    inset   = polygon.buffer(-clearance)
    if inset.is_empty:
        inset = polygon

    minx, miny, maxx, maxy = inset.bounds

    # Snap to global grid origin (0,0)
    start_x = math.ceil(minx / pitch_x) * pitch_x
    start_y = math.ceil(miny / pitch_y) * pitch_y

    candidates = []
    x = start_x
    while x <= maxx:
        y = start_y
        while y <= maxy:
            pt = Point(x, y)
            if inset.contains(pt):
                candidates.append((x, y))
            y += pitch_y
        x += pitch_x

    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# Spacing / selection helpers
# ─────────────────────────────────────────────────────────────────────────────

def min_luminaire_count(zone: ZoneResult,
                        zone_cfg: ZoneConfig,
                        luminaire: LuminaireSpec) -> int:
    """
    Estimate minimum luminaire count from lux target.
    Uses simple lumen method: n = (E × A) / (Φ × LLF × UF)
    where LLF=0.8, UF=0.7 (conservative estimates).
    """
    E   = zone_cfg.lux_target   # target lux
    A   = zone.area_m2          # m²
    phi = luminaire.lux_output  # lm per luminaire
    LLF = 0.80
    UF  = 0.70
    n   = (E * A) / (phi * LLF * UF)
    return max(1, math.ceil(n))


def greedy_spacing_filter(candidates: list[tuple],
                          min_spacing: float = MIN_LUMI_SPACING
                          ) -> list[tuple]:
    """
    Greedy filter: keep a candidate only if it is ≥ min_spacing from
    all already-kept candidates.  O(n²) but n is small per zone.
    """
    kept = []
    for cand in candidates:
        too_close = any(
            math.dist(cand, k) < min_spacing for k in kept
        )
        if not too_close:
            kept.append(cand)
    return kept


# ─────────────────────────────────────────────────────────────────────────────
# Shelf-alignment pass
# ─────────────────────────────────────────────────────────────────────────────

def shelf_aligned_candidates(
        shelves: list[FurnitureInsert],
        polygon: Polygon,
        lumi_length_mm: float,
        pitch_x: float,
        pitch_y: float,
        clearance: float = MIN_WALL_CLEARANCE,
) -> list[tuple[float, float]]:
    """
    Place luminaires centred above shelf runs.
    Shelves are assumed to run parallel to X or Y axis.
    We project shelf centrelines and snap to nearest grid.
    """
    candidates = []
    inset = polygon.buffer(-clearance)

    for shelf in shelves:
        sx, sy = shelf.position
        # Snap to grid
        gx = round(sx / pitch_x) * pitch_x
        gy = round(sy / pitch_y) * pitch_y
        pt = Point(gx, gy)
        if inset.is_empty or inset.contains(pt):
            candidates.append((gx, gy))

    return list(set(candidates))


# ─────────────────────────────────────────────────────────────────────────────
# Main placer
# ─────────────────────────────────────────────────────────────────────────────

class LuminairePlacer:

    def __init__(self, pitch_x: float = GRID_PITCH_MM,
                       pitch_y: float = GRID_PITCH_MM):
        self.pitch_x = pitch_x
        self.pitch_y = pitch_y

    def place_all(self,
                  plan: ParsedPlan,
                  selections: list[SelectionResult],
                  zone_configs: dict[str, ZoneConfig],
                  ) -> PlacementResult:

        # Override pitch from detected grid if available
        if plan.grid_lines:
            self.pitch_x, self.pitch_y = detect_grid_pitch(plan.grid_lines)

        result = PlacementResult(source_file=plan.source_file)

        for sel in selections:
            zone    = sel.zone_result
            lumi    = sel.luminaire
            zone_cfg = zone_configs.get(zone.zone_type)
            if zone_cfg is None:
                continue

            placed = self._place_zone(zone, lumi, zone_cfg, plan)
            result.placed.extend(placed)

        return result

    def _place_zone(self,
                    zone: ZoneResult,
                    lumi: LuminaireSpec,
                    zone_cfg: ZoneConfig,
                    plan: ParsedPlan,
                    ) -> list[PlacedLuminaire]:

        poly = zone.polygon

        if zone_cfg.spacing_rule == "shelf_aligned":
            return self._place_shelf_aligned(zone, lumi, zone_cfg, plan)
        elif zone_cfg.spacing_rule == "perimeter":
            return self._place_perimeter(zone, lumi, zone_cfg)
        else:
            return self._place_grid(zone, lumi, zone_cfg)

    # ── Grid-aligned placement ────────────────────────────────────────────────

    def _place_grid(self,
                    zone: ZoneResult,
                    lumi: LuminaireSpec,
                    zone_cfg: ZoneConfig,
                    ) -> list[PlacedLuminaire]:

        candidates = generate_grid_candidates(
            zone.polygon, self.pitch_x, self.pitch_y,
            zone_cfg.rows_from_wall_mm,
        )

        n_required = min_luminaire_count(zone, zone_cfg, lumi)

        # Thin to spacing constraint
        filtered = greedy_spacing_filter(candidates, MIN_LUMI_SPACING)

        # If not enough after filtering, relax spacing
        if len(filtered) < n_required and candidates:
            relaxed = MIN_LUMI_SPACING * 0.7
            filtered = greedy_spacing_filter(candidates, relaxed)

        # Trim to required count, evenly distributed
        if len(filtered) > n_required * 3:
            step = len(filtered) // n_required
            filtered = filtered[::step][:n_required * 2]

        return [
            PlacedLuminaire(
                x=x, y=y,
                luminaire=lumi,
                zone_type=zone.zone_type,
                mounting_type=lumi.mounting_type,
                is_snapped_to_grid=True,
            )
            for x, y in filtered
        ]

    # ── Shelf-aligned placement ───────────────────────────────────────────────

    def _place_shelf_aligned(self,
                             zone: ZoneResult,
                             lumi: LuminaireSpec,
                             zone_cfg: ZoneConfig,
                             plan: ParsedPlan,
                             ) -> list[PlacedLuminaire]:

        # Shelves inside this zone
        shelves = [
            fi for fi in plan.furniture
            if fi.inferred_type == "shelving"
            and zone.polygon.contains(Point(fi.position))
        ]

        placed: list[PlacedLuminaire] = []

        if shelves:
            shelf_cands = shelf_aligned_candidates(
                shelves, zone.polygon, lumi.length_mm,
                self.pitch_x, self.pitch_y, zone_cfg.rows_from_wall_mm,
            )
            filtered = greedy_spacing_filter(shelf_cands, MIN_LUMI_SPACING)
            placed = [
                PlacedLuminaire(
                    x=x, y=y,
                    luminaire=lumi,
                    zone_type=zone.zone_type,
                    mounting_type=lumi.mounting_type,
                    is_snapped_to_grid=True,
                    aligned_to_shelf=True,
                )
                for x, y in filtered
            ]

        # If shelf placement gives too few, supplement with grid
        n_required = min_luminaire_count(zone, zone_cfg, lumi)
        if len(placed) < n_required:
            grid_placed = self._place_grid(zone, lumi, zone_cfg)
            # Only add grid positions not close to existing shelf positions
            existing = [(p.x, p.y) for p in placed]
            for gp in grid_placed:
                if not any(math.dist((gp.x, gp.y), e) < MIN_LUMI_SPACING
                           for e in existing):
                    placed.append(gp)
                    existing.append((gp.x, gp.y))

        return placed

    # ── Perimeter placement (corridors) ──────────────────────────────────────

    def _place_perimeter(self,
                         zone: ZoneResult,
                         lumi: LuminaireSpec,
                         zone_cfg: ZoneConfig,
                         ) -> list[PlacedLuminaire]:
        """Place luminaires along the centreline of a corridor."""
        poly  = zone.polygon
        # Approximate centreline as medial axis (simplified: use centroid row)
        bounds = poly.bounds
        cx = (bounds[0] + bounds[2]) / 2
        cy = (bounds[1] + bounds[3]) / 2

        # Determine dominant axis
        width  = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        placed = []

        spacing = max(lumi.length_mm * 1.5, MIN_LUMI_SPACING)

        if width > height:
            # Horizontal corridor — place along Y centre
            x = bounds[0] + spacing / 2
            while x < bounds[2]:
                pt = Point(x, cy)
                if poly.contains(pt):
                    placed.append(PlacedLuminaire(
                        x=x, y=cy, luminaire=lumi,
                        zone_type=zone.zone_type,
                        mounting_type=lumi.mounting_type,
                        rotation=90.0,
                        is_snapped_to_grid=False,
                    ))
                x += spacing
        else:
            # Vertical corridor — place along X centre
            y = bounds[1] + spacing / 2
            while y < bounds[3]:
                pt = Point(cx, y)
                if poly.contains(pt):
                    placed.append(PlacedLuminaire(
                        x=cx, y=y, luminaire=lumi,
                        zone_type=zone.zone_type,
                        mounting_type=lumi.mounting_type,
                        rotation=0.0,
                        is_snapped_to_grid=False,
                    ))
                y += spacing

        return placed


# ─────────────────────────────────────────────────────────────────────────────
# CLI smoke test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from shapely.geometry import box as shapely_box
    from services.classifier.room_classifier import ZoneResult
    from services.classifier.luminaire_selector import (
        load_concept, LuminaireSelector, DEFAULT_CONCEPT_YAML
    )
    from services.parser.dwg_parser import ParsedPlan, FurnitureInsert

    # Ensure concept exists
    default_path = CONCEPTS_DIR / "default_retail.yaml"
    if not default_path.exists():
        default_path.write_text(DEFAULT_CONCEPT_YAML)

    concept  = load_concept("default_retail")
    selector = LuminaireSelector("default_retail")
    placer   = LuminairePlacer()

    # Synthetic plan
    plan = ParsedPlan(source_file="synthetic_test")
    plan.room_polygons = [
        shapely_box(0, 0, 15000, 12000),      # sales floor 180 m²
        shapely_box(15000, 0, 18000, 5000),   # checkout 15 m²
    ]
    plan.furniture = [
        FurnitureInsert("SHELF_1200", (3000, 3000), 0, "FURNITURE", "shelving"),
        FurnitureInsert("SHELF_1200", (6000, 3000), 0, "FURNITURE", "shelving"),
        FurnitureInsert("SHELF_1200", (9000, 3000), 0, "FURNITURE", "shelving"),
        FurnitureInsert("SHELF_1200", (3000, 7000), 0, "FURNITURE", "shelving"),
        FurnitureInsert("SHELF_1200", (6000, 7000), 0, "FURNITURE", "shelving"),
        FurnitureInsert("POS_DESK",  (16500,2500), 0, "CHECKOUT",  "checkout"),
    ]

    fake_zones = [
        ZoneResult(0, plan.room_polygons[0], "sales_floor", 0.90, "rule",
                   {"shelving": 5}, area_m2=180.0),
        ZoneResult(1, plan.room_polygons[1], "checkout_zone", 0.95, "rule",
                   {"checkout": 1}, area_m2=15.0),
    ]

    selections   = selector.select_all(fake_zones)
    zone_configs = {z: concept.get_zone_config(z)
                    for z in ["sales_floor", "checkout_zone"]}

    result = placer.place_all(plan, selections, zone_configs)
    print(result.summary())

    for zone_t in ["sales_floor", "checkout_zone"]:
        by_z = result.by_zone(zone_t)
        print(f"  {zone_t}: {len(by_z)} luminaires")
        for p in by_z[:3]:
            print(f"    ({p.x:.0f}, {p.y:.0f}) {p.luminaire.product_code} "
                  f"shelf={p.aligned_to_shelf} grid={p.is_snapped_to_grid}")