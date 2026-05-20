"""
lighting-ai/services/classifier/luminaire_selector.py

Layer 4 — Luminaire Selection (M4, M5)

Loads customer concept YAML files and maps zone types to luminaires.
Falls back to XGBoost for ambiguous cases.
"""
from __future__ import annotations
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import CONCEPTS_DIR
from services.classifier.room_classifier import ZoneResult


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LuminaireSpec:
    product_code: str
    description: str
    wattage: float
    lux_output: float          # lm at 1m (used for spacing calc)
    mounting_type: str         # "grid_recessed" | "surface" | "pendant"
    length_mm: float = 0.0
    width_mm:  float = 0.0
    ip_rating: str  = "IP20"
    dimmable:  bool = True


@dataclass
class ZoneConfig:
    zone_type: str
    primary:   LuminaireSpec
    secondary: Optional[LuminaireSpec]
    lux_target: float
    spacing_rule: str          # "grid_aligned" | "shelf_aligned" | "perimeter"
    rows_from_wall_mm: float = 300.0


@dataclass
class ConceptModel:
    concept_id: str
    customer:   str
    version:    str
    zones:      dict[str, ZoneConfig]   # zone_type → ZoneConfig

    def get_zone_config(self, zone_type: str) -> Optional[ZoneConfig]:
        return self.zones.get(zone_type) or self.zones.get("default")


@dataclass
class SelectionResult:
    zone_result: ZoneResult
    luminaire:   LuminaireSpec
    is_secondary: bool = False
    confidence:   float = 1.0
    reason:       str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Concept YAML schema + loader
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CONCEPT_YAML = """\
concept_id: "default_retail"
customer: "Default"
version: "1.0.0"
zones:
  sales_floor:
    primary_luminaire:
      product_code: "LX-400-LED"
      description: "Recessed LED panel 40W"
      wattage: 40
      lux_output: 4000
      mounting_type: "grid_recessed"
      length_mm: 600
      width_mm: 600
      ip_rating: "IP40"
      dimmable: true
    secondary_luminaire:
      product_code: "LX-200-LED"
      description: "Recessed LED panel 20W"
      wattage: 20
      lux_output: 2000
      mounting_type: "grid_recessed"
      length_mm: 600
      width_mm: 300
      ip_rating: "IP40"
      dimmable: true
    lux_target: 750
    spacing_rule: "shelf_aligned"
    rows_from_wall_mm: 300

  checkout_zone:
    primary_luminaire:
      product_code: "LX-300-LED"
      description: "Surface LED strip 30W"
      wattage: 30
      lux_output: 3000
      mounting_type: "surface"
      length_mm: 1200
      width_mm: 100
      ip_rating: "IP40"
      dimmable: true
    lux_target: 500
    spacing_rule: "grid_aligned"
    rows_from_wall_mm: 300

  entrance:
    primary_luminaire:
      product_code: "LX-100-LED"
      description: "Recessed downlight 10W"
      wattage: 10
      lux_output: 1000
      mounting_type: "grid_recessed"
      length_mm: 200
      width_mm: 200
      ip_rating: "IP44"
      dimmable: true
    lux_target: 300
    spacing_rule: "grid_aligned"
    rows_from_wall_mm: 400

  storage:
    primary_luminaire:
      product_code: "LX-150-LED"
      description: "Batten LED 15W"
      wattage: 15
      lux_output: 1500
      mounting_type: "surface"
      length_mm: 1200
      width_mm: 80
      ip_rating: "IP40"
      dimmable: false
    lux_target: 200
    spacing_rule: "grid_aligned"
    rows_from_wall_mm: 200

  corridor:
    primary_luminaire:
      product_code: "LX-150-LED"
      description: "Batten LED 15W"
      wattage: 15
      lux_output: 1500
      mounting_type: "surface"
      length_mm: 1200
      width_mm: 80
      ip_rating: "IP40"
      dimmable: true
    lux_target: 200
    spacing_rule: "perimeter"
    rows_from_wall_mm: 200

  office:
    primary_luminaire:
      product_code: "LX-400-LED"
      description: "Recessed LED panel 40W"
      wattage: 40
      lux_output: 4000
      mounting_type: "grid_recessed"
      length_mm: 600
      width_mm: 600
      ip_rating: "IP40"
      dimmable: true
    lux_target: 500
    spacing_rule: "grid_aligned"
    rows_from_wall_mm: 300

  default:
    primary_luminaire:
      product_code: "LX-200-LED"
      description: "Recessed LED panel 20W"
      wattage: 20
      lux_output: 2000
      mounting_type: "grid_recessed"
      length_mm: 600
      width_mm: 300
      ip_rating: "IP40"
      dimmable: true
    lux_target: 300
    spacing_rule: "grid_aligned"
    rows_from_wall_mm: 300
"""


def _parse_lumi(data: dict) -> LuminaireSpec:
    return LuminaireSpec(
        product_code  = data["product_code"],
        description   = data["description"],
        wattage       = data["wattage"],
        lux_output    = data["lux_output"],
        mounting_type = data["mounting_type"],
        length_mm     = data.get("length_mm", 600),
        width_mm      = data.get("width_mm", 600),
        ip_rating     = data.get("ip_rating", "IP20"),
        dimmable      = data.get("dimmable", True),
    )


def load_concept(concept_id: str) -> ConceptModel:
    """
    Load a concept YAML from CONCEPTS_DIR/{concept_id}.yaml.
    Falls back to the built-in default if not found.
    """
    yaml_path = CONCEPTS_DIR / f"{concept_id}.yaml"

    if yaml_path.exists():
        raw = yaml.safe_load(yaml_path.read_text())
    else:
        # Write default and use it
        default_path = CONCEPTS_DIR / "default_retail.yaml"
        if not default_path.exists():
            default_path.write_text(DEFAULT_CONCEPT_YAML)
        raw = yaml.safe_load(DEFAULT_CONCEPT_YAML)

    zones = {}
    for zone_type, cfg in raw["zones"].items():
        primary   = _parse_lumi(cfg["primary_luminaire"])
        secondary = (_parse_lumi(cfg["secondary_luminaire"])
                     if "secondary_luminaire" in cfg else None)
        zones[zone_type] = ZoneConfig(
            zone_type        = zone_type,
            primary          = primary,
            secondary        = secondary,
            lux_target       = cfg.get("lux_target", 300),
            spacing_rule     = cfg.get("spacing_rule", "grid_aligned"),
            rows_from_wall_mm= cfg.get("rows_from_wall_mm", 300),
        )

    return ConceptModel(
        concept_id = raw["concept_id"],
        customer   = raw.get("customer", ""),
        version    = raw.get("version", "1.0"),
        zones      = zones,
    )


def list_concepts() -> list[str]:
    return [p.stem for p in CONCEPTS_DIR.glob("*.yaml")]


# ─────────────────────────────────────────────────────────────────────────────
# Selector
# ─────────────────────────────────────────────────────────────────────────────

class LuminaireSelector:
    def __init__(self, concept_id: str = "default_retail"):
        self.concept = load_concept(concept_id)

    def select(self, zone: ZoneResult) -> SelectionResult:
        zone_cfg = self.concept.get_zone_config(zone.zone_type)

        if zone_cfg is None:
            # Absolute fallback
            zone_cfg = self.concept.get_zone_config("default")

        # Use secondary if zone area is small and secondary exists
        use_secondary = (
            zone_cfg.secondary is not None
            and zone.area_m2 < 25
            and zone.zone_type == "sales_floor"
        )

        luminaire = (zone_cfg.secondary if use_secondary
                     else zone_cfg.primary)
        reason    = ("secondary (small zone)" if use_secondary
                     else "primary (standard)")

        return SelectionResult(
            zone_result  = zone,
            luminaire    = luminaire,
            is_secondary = use_secondary,
            confidence   = zone.confidence,
            reason       = reason,
        )

    def select_all(self, zones: list[ZoneResult]) -> list[SelectionResult]:
        return [self.select(z) for z in zones]


# ─────────────────────────────────────────────────────────────────────────────
# CLI smoke test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from shapely.geometry import box
    from services.classifier.room_classifier import ZoneResult

    # Ensure default concept YAML exists
    default_path = CONCEPTS_DIR / "default_retail.yaml"
    if not default_path.exists():
        default_path.write_text(DEFAULT_CONCEPT_YAML)
    print(f"Concepts available: {list_concepts()}")

    concept = load_concept("default_retail")
    print(f"Loaded concept: {concept.concept_id} v{concept.version} "
          f"for {concept.customer}")
    print(f"Zones configured: {list(concept.zones.keys())}")

    # Fake zone results
    fake_zones = [
        ZoneResult(0, box(0,0,10000,8000), "sales_floor", 0.90, "rule",
                   {"shelving": 5}, 80.0),
        ZoneResult(1, box(10000,0,12000,3000), "checkout_zone", 0.95, "rule",
                   {"checkout": 2}, 6.0),
    ]

    selector = LuminaireSelector("default_retail")
    results  = selector.select_all(fake_zones)
    for r in results:
        print(f"  {r.zone_result.zone_type} → "
              f"{r.luminaire.product_code} "
              f"({r.luminaire.wattage}W, {r.luminaire.lux_output}lm) "
              f"[{r.reason}]")