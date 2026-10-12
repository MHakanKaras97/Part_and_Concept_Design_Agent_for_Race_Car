"""Part colours (cosmetic): ONE project data file, <project>/palette.json, used by every build, rebuild, derive and
by "Apply palette" (recolour in place, no geometry change).

    {"palette_version": 1, "parts": {"MON-001": {"color": "#B01E28", "finish": "glossy_paint",
                                                 "zones": [{"rule": "cockpit", "color": "#CBD0D8"}]}, ...}}

A derived (mirror_of) part not listed uses its source's entry; a part listed nowhere gets the built-in default
colour of its prefix. Zones colour selected FACES of a part by a deterministic face rule (appearance only, the
geometry is untouched):
- wheel_rim: the outboard rim face disc with its lip and spoke ribs. Part-local frame, axle = local Y, rim recessed
  on +Y: a face whose bbox stays within radius rim_diameter/2 (+0.5 mm) of the axle and starts no deeper than the
  recessed rim face (width/2 - rim_recess_depth, -2 mm for ribs sunk into it). Needs those three dims.
- cockpit: the cockpit rim ring and everything inside it. The rim top is the ONLY planar face at the body's highest
  Z; every face whose XY bbox lies inside that face's XY bbox (+1 mm) is selected. No unique top face -> skipped.
Colour is not part of a part's spec or script, so it never affects the spec / script hash or the part version:
changing the palette never creates a new part version.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from vehicle.parts import PART_ID_PATTERN

FILENAME = "palette.json"
Finish = Literal["glossy_paint", "matte_rubber", "satin"]
FINISHES = ("glossy_paint", "matte_rubber", "satin")
ZoneRule = Literal["wheel_rim", "cockpit"]
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Built-in defaults (no palette file, or a part not listed): readable screenshot colours by part-id prefix.
DEFAULT_COLORS = {"MON": "#DC1E28", "FWG": "#1E6EE6", "FLR": "#28282D", "RWG": "#FAAA14", "WHL": "#191919",
                  "SUF": "#787882", "SUR": "#787882", "SDP": "#C82832", "ENG": "#A01E23", "HAL": "#3C3C46",
                  "MIR": "#E6E6EB"}
DEFAULT_COLOR = "#B4B4B9"
DEFAULT_FINISHES = {"WHL": "matte_rubber", "SUF": "satin", "SUR": "satin", "FLR": "satin"}


def _hex(v: str) -> str:
    if not isinstance(v, str) or not HEX_RE.match(v):
        raise ValueError(f"colour {v!r} is not a #RRGGBB hex value")
    return v.upper()


def _rgb(hexv: str) -> list[int]:
    return [int(hexv[i:i + 2], 16) for i in (1, 3, 5)]


class ZoneEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rule: ZoneRule
    color: str
    finish: Finish = "glossy_paint"

    @field_validator("color")
    @classmethod
    def _color_hex(cls, v: str) -> str:
        return _hex(v)


class PaletteEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    color: str
    finish: Finish = "glossy_paint"
    zones: tuple[ZoneEntry, ...] = ()

    @field_validator("color")
    @classmethod
    def _color_hex(cls, v: str) -> str:
        return _hex(v)

    @field_validator("zones")
    @classmethod
    def _one_per_rule(cls, v):
        rules = [z.rule for z in v]
        if len(rules) != len(set(rules)):
            raise ValueError(f"a zone rule may appear once per part (got {rules})")
        return v


class Palette(BaseModel):
    model_config = ConfigDict(extra="forbid")
    palette_version: Literal[1] = 1
    note: str = ""
    parts: dict[str, PaletteEntry] = Field(default_factory=dict)

    @field_validator("parts")
    @classmethod
    def _ids(cls, v: dict) -> dict:
        bad = [k for k in v if not re.fullmatch(PART_ID_PATTERN, k)]
        if bad:
            raise ValueError(f"not part ids: {bad}")
        return v


class Paint(BaseModel):
    """What a part is painted with: resolved colour + finish (+ face zones), and where it came from."""
    model_config = ConfigDict(frozen=True)
    hex: str
    finish: Finish
    source: str                      # "palette" | "palette (source <ID>)" | "default"
    zones: tuple[ZoneEntry, ...] = ()

    @property
    def rgb(self) -> list[int]:
        return _rgb(self.hex)

    def cfg(self, dims: Optional[dict] = None) -> dict:
        """The build / recolour script's view of it; zones carry their rule parameters from the part's dims (a zone
        whose rule cannot apply carries "skip": reason instead)."""
        zones = []
        for z in self.zones:
            params, why = zone_params(z.rule, dims or {})
            zones.append(dict(rule=z.rule, color=_rgb(z.color), hex=z.color, finish=z.finish,
                              **(params if why is None else {"skip": why})))
        return {"color": self.rgb, "hex": self.hex, "finish": self.finish, "zones": zones}


def zone_params(rule: str, dims: dict) -> tuple[dict, Optional[str]]:
    """(rule parameters, None) or ({}, why the rule cannot apply to this part)."""
    if rule == "wheel_rim":
        need = ("rim_diameter", "width", "rim_recess_depth")
        missing = [k for k in need if k not in dims]
        if missing:
            return {}, f"wheel_rim needs the dims {', '.join(missing)}"
        return {"rim_radius": dims["rim_diameter"] / 2.0,
                "rim_face_y": dims["width"] / 2.0 - dims["rim_recess_depth"]}, None
    if rule == "cockpit":
        return {}, None
    return {}, f"unknown zone rule {rule}"


def palette_path(project_root: Path) -> Path:
    return Path(project_root) / FILENAME


def parse_palette(data) -> Palette:
    """Validate palette data; ValueError with a readable message on any problem (bad hex, unknown finish, ...)."""
    try:
        return Palette.model_validate(data)
    except ValidationError as e:
        msgs = ["/".join(str(x) for x in err["loc"]) + ": " + err["msg"] for err in e.errors()]
        raise ValueError("invalid palette: " + "; ".join(msgs)) from None


def load_palette(project_root: Path) -> Optional[Palette]:
    """The project's palette, or None when it has no palette file. Raises ValueError when the file is invalid."""
    p = palette_path(project_root)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid palette: {p.name} is not JSON ({e})") from None
    return parse_palette(data)


def palette_sha256(project_root: Path) -> Optional[str]:
    p = palette_path(project_root)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def paint_for(part_id: str, mirror_of: Optional[str] = None, palette: Optional[Palette] = None) -> Paint:
    """The part's own palette entry, else its source's (derived parts), else the built-in default of its prefix."""
    parts = palette.parts if palette else {}
    if part_id in parts:
        e = parts[part_id]
        return Paint(hex=e.color, finish=e.finish, source="palette", zones=e.zones)
    if mirror_of and mirror_of in parts:
        e = parts[mirror_of]
        return Paint(hex=e.color, finish=e.finish, source=f"palette (source {mirror_of})", zones=e.zones)
    prefix = part_id.split("-")[0]
    return Paint(hex=DEFAULT_COLORS.get(prefix, DEFAULT_COLOR), finish=DEFAULT_FINISHES.get(prefix, "glossy_paint"),
                 source="default")
