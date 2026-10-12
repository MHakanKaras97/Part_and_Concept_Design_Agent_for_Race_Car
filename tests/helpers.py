"""Shared test data and TEST DOUBLES.

FakeFusion and ScriptedBackend exist only to test the deterministic workflow logic without a
running Fusion or an AI. They are never used at runtime; real CAD is covered by tests/integration.
"""
from __future__ import annotations

import json
import math

import numpy as np

from fusion.client import FusionScriptError, FusionUnavailable, ScriptResult
from fusion.generators import l_bracket as g
from vehicle.transforms import transform_point, transform_vector

GOOD = dict(leg_base_length=80, leg_upright_height=70, bracket_width=60, bracket_thickness=6, bend_inner_radius=4,
            base_hole_diameter=6.6, base_hole_x0=35, base_hole_pitch_x=30, base_hole_pitch_y=36,
            upright_hole_diameter=5.5, upright_hole_z0=30, upright_hole_pitch_z=28, upright_hole_pitch_y=36,
            base_hole_rows=2, base_hole_cols=2, upright_hole_rows=2, upright_hole_cols=2)
FASTENERS = {"base_fastener": "M6", "upright_fastener": "M5"}


def good_inputs(**over) -> g.BracketInputs:
    v = dict(GOOD, **over)
    return g.BracketInputs.from_values(v, FASTENERS)


REQUEST = ("Design a machined aluminium 6061 L-bracket for a sensor box, base bolted with M6, "
           "upright bolted with M5, compact envelope.")
LOAD_QUESTION = "What load must the bracket carry, and in which direction?"
QUOTES = {"function": "L-bracket for a sensor box", "material": "aluminium 6061", "manufacturing_process": "machined",
          "base_fastener": "base bolted with M6", "upright_fastener": "upright bolted with M5",
          "envelope": "compact envelope"}


def analysis_response(ask_load: bool = False, critical_assumed: bool = False, load_answer: str | None = None,
                      answer_id: str = "M01") -> dict:
    """load_answer: verbatim excerpt of the user's answer used to interpret the load requirement."""
    reqs = [{"id": f"R{i + 1:02d}", "key": k, "text": f"{k} as stated in the request", "source": "USER_REQUEST",
             "quote": q} for i, (k, q) in enumerate(QUOTES.items())]
    if load_answer is not None:
        reqs.append({"id": "R07", "key": "load", "text": f"Load case: {load_answer}", "source": "USER_ANSWER",
                     "answer_id": answer_id, "quote": load_answer})
        missing = [{"id": "M01", "key": "load", "topic": "Load case", "why_it_matters": "sizing",
                    "criticality": "CRITICAL", "resolution": "ASK", "question": LOAD_QUESTION}]
        return {"component_type": "l_bracket", "summary": "L-bracket", "requirements": reqs,
                "missing_information": missing, "assumptions": [{"id": "A01", "text": "Concept-level", "rationale": "MVP"}]}
    if ask_load:
        missing = [{"id": "M01", "key": "load", "topic": "Load case", "why_it_matters": "sizing",
                    "criticality": "CRITICAL", "resolution": "ASK", "question": LOAD_QUESTION}]
        assumptions = [{"id": "A01", "text": "Concept-level", "rationale": "MVP"}]
    elif critical_assumed:
        missing = [{"id": "M01", "key": "load", "topic": "Load case", "why_it_matters": "sizing",
                    "criticality": "CRITICAL", "resolution": "ASSUME", "assumption_id": "A01"}]
        assumptions = [{"id": "A01", "text": "5 g load", "rationale": "typical"}]
    else:
        missing = [{"id": "M01", "key": "load", "topic": "Load case", "why_it_matters": "sizing",
                    "criticality": "IMPORTANT", "resolution": "ASSUME", "assumption_id": "A01"}]
        assumptions = [{"id": "A01", "text": "2 kg payload, 5 g dynamic factor", "rationale": "vibration"}]
    return {"component_type": "l_bracket", "summary": "L-bracket", "requirements": reqs,
            "missing_information": missing, "assumptions": assumptions}


def plan_response(**over) -> dict:
    params = {}
    for k, v in dict(GOOD, **over).items():
        unit = "count" if k in g.COUNT_PARAMS else "mm"
        params[k] = {"value": v, "unit": unit, "source": "ASSUMPTION", "trace": ["A01"], "rationale": "test"}
    return {"generator": "l_bracket", "component_name": "Sensor bracket", "steps": ["build", "check"],
            "parameters": params,
            "design_inputs": dict(FASTENERS, base_mates_with="plate", upright_mates_with="sensor_box"),
            "manufacturing": {"process": "machined", "material": "AL6061-T6"},
            "load_case": {"description": "2 kg x 5 g at 40 mm", "force_n": 98.1, "lever_arm_mm": 40,
                          "required_safety_factor": 2.0, "trace": ["A01"]},
            "verification_plan": ["measure in Fusion"]}


class ScriptedBackend:
    """Answers reasoning tasks from a dict kind -> list of responses (consumed in order)."""

    def __init__(self, responses: dict[str, list[dict]]):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.tasks = []

    def request(self, task):
        self.tasks.append(task)
        queue = self.responses.get(task.kind)
        return queue.pop(0) if queue else None


def _cfg(script: str) -> dict:
    return json.loads(script.split('r"""')[1].split('"""')[0])


class FakeFusion:
    """Pretends to be a perfect CAD system: reports exactly the geometry the generator intends."""

    def __init__(self, fail_build: bool = False, unavailable: bool = False, volume_scale: float = 1.0,
                 lose_output: bool = False, inspect_version: str = "test"):
        self.fail_build, self.unavailable, self.volume_scale = fail_build, unavailable, volume_scale
        self.inspect_version = inspect_version   # Fusion build reported by the inspection (the build reports "test")
        self.lose_output = lose_output        # success with no @@RESULT@@ line (degraded MCP output channel)
        self.built = {}

    def connect(self) -> dict:
        if self.unavailable:
            raise FusionUnavailable("test: fusion down")
        return {"serverInfo": {"name": "fake"}}

    def run_script(self, script: str, read_only: bool = False) -> ScriptResult:
        if self.unavailable:
            raise FusionUnavailable("test: fusion down")
        if self.lose_output:
            return ScriptResult("", None)
        cfg = _cfg(script)
        if not read_only:
            if self.fail_build:
                raise FusionScriptError("Fusion script failed: RuntimeError: test failure", "traceback...")
            self.built[cfg["component_name"]] = cfg
            return ScriptResult("", {"component_name": cfg["component_name"], "body_name": cfg["body_name"],
                                     "document": "Untitled", "fusion_version": "test", "material": None, "warnings": []})
        name = cfg["component_name"]
        if name not in self.built:
            return ScriptResult("", {"found": False, "component_name": name})
        b = self.built[name]
        p = g.BracketInputs.model_validate(b["values"])
        lo, hi = g.expected_bbox_local(p)
        m = np.array(b["transform"], dtype=float).reshape(4, 4)
        m[:3, 3] *= 10.0                                         # the build script receives cm
        L, H, tb, tu, w2 = p.leg_base_length, p.leg_upright_height, p.bracket_thickness, p.upright_t, p.bracket_width / 2
        local = [[x, y, z] for x, z in [(0, 0), (L, 0), (L, tb), (tu, tb), (tu, H), (0, H)] for y in (-w2, w2)]
        world = [transform_point(m, tuple(v)) for v in local]  # stand-in vertices: the L profile corners
        cyl = [{"center": list(transform_point(m, h["center"])), "axis": list(transform_vector(m, h["axis"])),
                "radius": h["diameter"] / 2, "concave": True} for h in g.expected_holes_local(p)]
        params = {f"{b['prefix']}_{k}": {"value_mm": v, "expression": f"{v} mm", "unit": "mm"}
                  for k, v, _ in b["params"]}
        params[f"{b['prefix']}_bend_outer_radius"] = {"value_mm": p.outer_radius, "expression": "", "unit": "mm"}
        return ScriptResult("", {
            "found": True, "component_name": name, "document": "Untitled", "fusion_version": self.inspect_version,
            "bodies": [{"name": b["body_name"], "is_solid": True, "volume_mm3": g.expected_volume_mm3(p) * self.volume_scale,
                        "area_mm2": 1.0, "bbox_min": list(np.min(world, axis=0)), "bbox_max": list(np.max(world, axis=0)),
                        "material": None, "cylinders": cyl, "bbox_local_min": list(lo), "bbox_local_max": list(hi),
                        "vertices_local": local, "vertices_world": [list(v) for v in world]}],
            "features": [{"name": "EX_L_profile", "type": "ExtrudeFeature", "health": "HEALTHY", "message": ""}],
            "sketches": [{"name": "SK_L_profile", "fully_constrained": True, "profiles": 1}],
            "parameters": params, "occurrence_transform": [float(v) for v in m.reshape(-1)],
            "pending_snapshot": False})

    def screenshot(self, **kw) -> bytes:
        return b"\x89PNG test"

    def ping(self) -> dict:
        if self.unavailable:
            raise FusionUnavailable("test: fusion down")
        return {"fusion_version": "test", "active_document": "Untitled", "has_design": True}


def assert_close(a, b, tol=1e-9):
    assert math.isclose(a, b, rel_tol=tol, abs_tol=tol), (a, b)


# ---------------------------------------------------------------- fast mode (free-form parts)
def decode_part_cfg(script: str) -> dict:
    """CFG of a composed prelude / assembly / camera script (base64 JSON)."""
    import base64
    import re
    m = re.search(r'b64decode\("([A-Za-z0-9+/=]+)"\)', script)
    return json.loads(base64.b64decode(m.group(1)).decode("utf-8"))


class FakePartFusion:
    """Pretends to be Fusion for fast-mode scripts. A body containing the text FAIL_AT_RUNTIME 'raises' at the
    line that contains it; one containing BBOX_TOO_BIG reports a bbox 100 mm larger than the envelope.
    The local bbox (frame check) is the envelope taken back by the inverse pose - a part-local script; a body
    containing WORLD_COORDS reports the envelope itself as its local bbox (a script that encodes the world position)
    and the pose then shifts it again. local_bboxes {part_id: (min, max)} sets a measured local bbox explicitly
    (the world bbox is then the pose applied to it). Records every script so tests can count calls.
    Documents: a build with create_doc=False into a document that was never created fails at stage "document"
    (close_document() simulates a closed one). geometric_mates=True measures mates from the built world bboxes
    (box distance / box overlap) instead of reporting every pair as touching. from_params=True: the local bbox is the
    box MINI_BOX_BODY builds from the length/width/height parameters ((0, -W/2, 0)..(L, W/2, H)), so a revised
    dimension or pose really changes the measured geometry. volumes {part_id: mm3} sets a part's measured volume
    (default 1000). Apply palette (recolour) reads back exactly what it was asked to apply, except: finishes in
    missing_finishes fall back to "plain", recolor_override {part_id: hex} simulates a wrong read-back colour; each
    zone paints zone_faces[rule] faces (default 3); stray_overrides {part_id: n} leaves n old face overrides."""

    def __init__(self, envelopes: dict | None = None, depth0: int = 1, lose_output_after: int | None = None,
                 unavailable: bool = False, local_bboxes: dict | None = None, geometric_mates: bool = False,
                 from_params: bool = False, volumes: dict | None = None):
        self.scripts, self.depth, self.screens = [], depth0, []
        self.envelopes = envelopes or {}          # part_id -> (min, max) reported as the measured world bbox
        self.local_bboxes = local_bboxes or {}
        self.geometric_mates = geometric_mates
        self.from_params = from_params
        self.volumes = volumes or {}
        self.missing_finishes: set[str] = set()
        self.recolor_override: dict[str, str] = {}
        self.recolors: list[dict] = []
        self.zone_faces: dict[str, int] = {}
        self.stray_overrides: dict[str, int] = {}
        self.docs: set[str] = set()
        self.boxes: dict[str, tuple] = {}         # part_id -> measured world bbox of its current build
        self.fail_next: dict[str, str] = {}       # part_id -> body marker to inject into its next build
        self.lose_output_after = lose_output_after
        self.unavailable = unavailable
        self.built: dict[str, dict] = {}
        # local render (fusion/render.py): render_mode ok | refuse | fail | never | lose_future; the job finishes
        # (or fails) after render_polls state checks; ok writes a real PNG header of the read-back size.
        self.render_mode = "ok"
        self.render_polls = 1
        self.render_readback: dict = {}            # overrides of the start script's settings read-back
        self.environments = ["Sharp Highlights", "Plaza"]
        self.active_tag: str | None = None          # None: the run's document is the active one
        self.render_jobs: dict[str, dict] = {}
        self.render_starts: list[dict] = []
        self.screen_sizes: list[tuple] = []
        self.viewport = [1920, 841]                  # the calibration's viewport (fusion/render_calibration.json)
        self.viewport_camera: dict | None = None     # eye/target the last render start set (preflight reads it)
        self.aims: list[dict] = []
        self.screenshot_png: bytes | None = None     # a real PNG returned by screenshot() when set
        # the finished render: a real PNG, background #3A3F47 with a light "car" box of this share of the frame,
        # centred (None: an empty frame)
        self.render_car = (0.34, 0.35)

    def close_document(self, doc_tag: str) -> None:
        self.docs.discard(doc_tag)

    def connect(self):
        if self.unavailable:
            raise FusionUnavailable("test: fusion down")
        return {}

    def ping(self):
        return {"fusion_version": "test", "active_document": "Untitled", "has_design": True}

    def run_script(self, script: str, read_only: bool = False, expect_result: bool = True) -> ScriptResult:
        from fusion.client import FusionOutputLost
        if self.unavailable:
            raise FusionUnavailable("test: fusion down")
        self.scripts.append(script)
        self.depth += 1
        if self.lose_output_after is not None and len(self.scripts) > self.lose_output_after:
            raise FusionOutputLost("test: output lost")
        cfg = decode_part_cfg(script)
        if cfg.get("probe"):                                    # read-only document probe (agent/revise.py)
            if cfg["doc_tag"] not in self.docs:
                return ScriptResult("", {"ok": False, "depth": self.depth, "present": {},
                                         "error": f"RuntimeError: design document '{cfg['doc_tag']}' is not open"})
            return ScriptResult("", {"ok": True, "depth": self.depth,
                                     "present": {k: k in self.built for k in cfg["keys"]}})
        if cfg.get("render_preflight") or cfg.get("render_start") or cfg.get("render_poll"):
            return ScriptResult("", self._render(cfg, read_only))
        if "keys" in cfg:                                       # assembly measurement
            ids = sorted(k for k in cfg["keys"] if k in self.built)
            always = {tuple(sorted(p)) for p in cfg.get("pairs", cfg["joints"])}
            pairs = [self._pair(a, b, (a, b) in always, cfg.get("near_mm", 1e9))
                     for i, a in enumerate(ids) for b in ids[i + 1:]]
            return ScriptResult("", {"ok": True, "depth": self.depth, "pairs": pairs, "joints": cfg["joints"],
                                     "missing": [k for k in cfg["keys"] if k not in self.built]})
        if cfg.get("recolor"):                                  # apply palette (fusion/paint.py)
            if self.depth > cfg["max_depth"]:
                return ScriptResult("", {"ok": False, "depth": self.depth, "parts": {},
                                         "error": f"MCP stdout wrapper depth {self.depth} > {cfg['max_depth']}"})
            if cfg["doc_tag"] not in self.docs:
                return ScriptResult("", {"ok": False, "depth": self.depth, "parts": {},
                                         "error": f"RuntimeError: design document '{cfg['doc_tag']}' is not open"})
            parts = {}
            for pid, p in cfg["parts"].items():
                if pid not in self.built:
                    parts[pid] = {"present": False}
                    continue
                fin = "plain" if p["finish"] in self.missing_finishes else p["finish"]
                hexv = self.recolor_override.get(pid, p["hex"])
                self.built[pid]["paint"] = dict(p, hex=hexv)
                zones = [{"rule": z["rule"], "faces": 0, "finish": None, "hex": [], "error": f"skipped: {z['skip']}"}
                         if z.get("skip") else
                         {"rule": z["rule"], "faces": self.zone_faces.get(z["rule"], 3),
                          "finish": "plain" if z["finish"] in self.missing_finishes else z["finish"],
                          "hex": [z["hex"]], "error": None} for z in p.get("zones", [])]
                parts[pid] = {"present": True, "bodies": 1, "finish": fin,
                              "applied": [{"appearance": f"agent {fin} {hexv[1:]}", "hex": hexv}], "zones": zones,
                              "face_overrides": sum(z["faces"] for z in zones) + self.stray_overrides.get(pid, 0)}
            self.recolors.append(cfg)
            return ScriptResult("", {"ok": True, "depth": self.depth, "parts": parts})
        if "eye" in cfg:                                        # camera
            return ScriptResult("", {"ok": True, "depth": self.depth, "z_up": True})
        body = script.split("# ---- BODY START ----\n", 1)[1].split("# ---- BODY END ----", 1)[0]
        res = {"ok": False, "stage": "body", "part_id": cfg["part_id"], "depth": self.depth,
               "fusion_version": "test", "created_document": False, "document": "Untitled"}
        if cfg["doc_tag"] not in self.docs:
            if not cfg.get("create_doc", True):
                res.update(stage="document", error=f"RuntimeError: design document '{cfg['doc_tag']}' is not open")
                return ScriptResult("", res)
            self.docs.add(cfg["doc_tag"])
            res["created_document"] = True
        self.built.pop(cfg["part_id"], None)                    # the prelude removes the previous build first
        self.boxes.pop(cfg["part_id"], None)
        if cfg["part_id"] in self.fail_next:
            body = body + chr(10) + self.fail_next.pop(cfg["part_id"])
        lines = body.splitlines()
        bad = [i + 1 for i, ln in enumerate(lines) if "FAIL_AT_RUNTIME" in ln]
        if bad:
            res.update(error="RuntimeError: test failure", body_lines=bad[:1])
            return ScriptResult("", res)
        m = np.array(cfg["matrix_cm"], dtype=float).reshape(4, 4)
        m[:3, 3] *= 10.0
        lo, hi = self.envelopes.get(cfg["part_id"], ([0, 0, 0], [10, 10, 10]))
        if "BBOX_TOO_BIG" in body:
            hi = [v + 100 for v in hi]
        prm = cfg["params"]
        if cfg["part_id"] in self.local_bboxes or (self.from_params and {"length", "width", "height"} <= set(prm)):
            if cfg["part_id"] in self.local_bboxes:
                local = [list(map(float, v)) for v in self.local_bboxes[cfg["part_id"]]]
            else:
                local = [[0.0, -prm["width"] / 2, 0.0], [prm["length"], prm["width"] / 2, prm["height"]]]
            if "WORLD_COORDS" in body and cfg["part_id"] not in self.local_bboxes:
                local = list(_box_through(m, *local))
            if "BBOX_TOO_BIG" in body:
                local[1] = [v + 100 for v in local[1]]
            if "SHORT_NOSE" in body:                            # the solid stops 20 mm short of its local -X face
                local[0] = [local[0][0] + 20.0] + local[0][1:]
            if cfg.get("mirror"):                               # the prelude's _mirror_y: y -> -y in the part frame
                local = [[local[0][0], -local[1][1], local[0][2]], [local[1][0], -local[0][1], local[1][2]]]
            lo, hi = _box_through(m, *local)
        elif "WORLD_COORDS" in body:
            local = [list(map(float, lo)), list(map(float, hi))]
            lo, hi = _box_through(m, *local)
        else:
            local = list(_box_through(np.linalg.inv(m), lo, hi))
        self.built[cfg["part_id"]] = cfg
        self.boxes[cfg["part_id"]] = (list(lo), list(hi))
        res.update(ok=True, stage="measure", placement={"applied": True, "pending": False}, warnings=[],
                   bbox_local=local,
                   measure={"bodies": [{"name": "Body1", "solid": True,
                                        "volume_mm3": float(self.volumes.get(cfg["part_id"], 1000.0))}],
                            "bbox_world": [list(lo), list(hi)], "features_total": 3, "features_bad": [],
                            "params": dict(cfg["params"]), "transform": [float(v) for v in m.reshape(-1)]})
        return ScriptResult("", res)

    def _render(self, cfg: dict, read_only: bool) -> dict:
        if cfg.get("render_preflight"):
            assert read_only, "the render preflight must be read-only"
            found = cfg["doc_tag"] in self.docs
            return {"ok": True, "depth": self.depth, "found": found, "documents": len(self.docs),
                    "active_tag": (self.active_tag or cfg["doc_tag"]) if found else self.active_tag,
                    "environments": list(self.environments) if found else None,
                    "scene": {"cameraType": "1", "environment": None} if found else None,
                    "viewport": list(self.viewport), "camera": self.viewport_camera}
        if cfg.get("render_start"):
            if self.depth > cfg["max_depth"]:
                return {"ok": False, "started": False, "depth": self.depth,
                        "error": f"MCP stdout wrapper depth {self.depth} > {cfg['max_depth']}"}
            if cfg["doc_tag"] not in self.docs:
                return {"ok": False, "started": False, "depth": self.depth,
                        "error": f"RuntimeError: design document '{cfg['doc_tag']}' is not open in Fusion"}
            frame = {"mode": cfg["camera"], "viewport": list(self.viewport),
                     "eye_cm": [10.0 * (len(self.render_starts) + 1), 1.0, 2.0], "target_cm": [0.0, 0.0, 0.0],
                     "planned_fill_true_lens": [0.7807, 0.8],
                     "nominal_focal_mm": 112.74 if cfg["field_scale"] != [1.0, 1.0] else cfg.get("focal_mm"),
                     "focal_read_back": 112.74, "look_focal_mm": cfg.get("focal_mm"), "distance_cm": 905.97}
            if cfg.get("aim_only"):
                self.aims.append(cfg)
                self.viewport_camera = {k: frame[k] for k in ("eye_cm", "target_cm")}
                return {"ok": True, "started": False, "depth": self.depth, "frame": frame}
            self.render_starts.append(cfg)
            self.viewport_camera = {k: frame[k] for k in ("eye_cm", "target_cm")}
            settings = dict({"aspect_custom": True, "width": cfg["width"], "height": cfg["height"],
                             "quality": cfg["quality"]}, **self.render_readback)
            if self.render_mode == "refuse":
                return {"ok": False, "started": False, "depth": self.depth, "settings": settings,
                        "error": "RuntimeError: rendering is not available"}
            self.render_jobs[cfg["token"]] = {"cfg": cfg, "left": self.render_polls, "settings": settings}
            return {"ok": True, "started": True, "depth": self.depth, "state": "queued", "progress": 0.0,
                    "settings": settings, "image": [settings["width"], settings["height"]], "filename": cfg["path"],
                    "frame": frame, "environment_read_back": "unreadable with a solid background"}
        job = self.render_jobs.get(cfg["token"])
        if job is None:
            return {"ok": True, "depth": self.depth, "known": False}
        job["left"] -= 1
        if job["left"] > 0 or self.render_mode == "never":
            return {"ok": True, "depth": self.depth, "known": True, "state": "processing", "progress": 0.5}
        if self.render_mode == "fail":
            return {"ok": True, "depth": self.depth, "known": True, "state": "failed", "progress": 0.5}
        from PIL import Image, ImageDraw
        w, h = job["settings"]["width"], job["settings"]["height"]
        im = Image.new("RGB", (w, h), (58, 63, 71))
        if self.render_car:
            cw, ch = int(w * self.render_car[0]), int(h * self.render_car[1])
            x0, y0 = (w - cw) // 2, (h - ch) // 2
            ImageDraw.Draw(im).rectangle([x0, y0, x0 + cw - 1, y0 + ch - 1], fill=(220, 40, 40))
        im.save(job["cfg"]["path"], "PNG")
        if self.render_mode == "lose_future":
            del self.render_jobs[cfg["token"]]
            return {"ok": True, "depth": self.depth, "known": False}
        return {"ok": True, "depth": self.depth, "known": True, "state": "finished", "progress": 1.0}

    def _pair(self, a: str, b: str, always: bool = True, near_mm: float = 1e9) -> dict:
        (alo, ahi), (blo, bhi) = self.boxes[a], self.boxes[b]
        sep = [max(alo[i] - bhi[i], blo[i] - ahi[i]) for i in range(3)]
        if not always and max(sep) > near_mm:                  # the assembly script's far-apart pair skip
            return {"a": a, "b": b, "skipped": "bounding boxes apart", "bbox_gap_mm": round(max(sep), 3)}
        if not self.geometric_mates:
            return {"a": a, "b": b, "min_distance_mm": 0.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
        apart = [max(v, 0.0) for v in sep]
        gap = float(sum(v * v for v in apart) ** 0.5)
        inside = all(v < 0 for v in sep)
        vol = float(np.prod([-v for v in sep])) if inside else 0.0
        return {"a": a, "b": b, "min_distance_mm": round(gap, 4), "overlap_mm3": round(vol, 3),
                "overlap_depth_mm": round(min(-v for v in sep), 4) if inside else 0.0}

    def screenshot(self, direction="iso-top-right", width=1200, height=800) -> bytes:
        self.screens.append(direction)
        self.screen_sizes.append((width, height))
        if self.screenshot_png is not None:
            return self.screenshot_png
        return b"\x89PNG test " + direction.encode()


def _box_through(m, lo, hi):
    """Axis-aligned box around the 8 corners of (lo, hi) mapped by the 4x4 matrix m (mm)."""
    pts = [m @ np.array([x, y, z, 1.0]) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    return ([round(float(min(p[i] for p in pts)), 4) + 0.0 for i in range(3)],
            [round(float(max(p[i] for p in pts)), 4) + 0.0 for i in range(3)])


MINI_BOX_BODY = '''def build(part):
    L, W, H = part.p["length"], part.p["width"], part.p["height"]
    sk = part.sketch(part.plane("z"), "SK_base")
    part.polygon(sk, [(0, -W / 2, 0), (L, -W / 2, 0), (L, W / 2, 0), (0, W / 2, 0)])
    part.extrude(part.profile(sk), "height", "EX_base")
'''


def mini_f1_plan(**over) -> dict:
    """A gate-valid Mini F1 plan (concept numbers for tests only)."""
    def part(pid, name, pos, lo, hi, refs=("C2.3.1",)):
        return {"id": pid, "name": name, "role": name.lower(), "notes": "", "position_mm": list(pos),
                "rotation_deg": [0, 0, 0], "envelope_min": list(lo), "envelope_max": list(hi),
                "dims": {"length": hi[0] - lo[0], "width": hi[1] - lo[1], "height": hi[2] - lo[2]},
                "fia_refs_used": list(refs), "reuse": False}
    plan = {"question": None,
            "parts": [part("MON-001", "Monocoque", (-2400, 0, 30), (-2400, -400, 30), (600, 400, 730)),
                      part("FWG-001", "Front wing", (600, 0, 60), (600, -900, 60), (1000, 900, 300)),
                      part("FLR-001", "Floor", (-3400, 0, 0), (-3400, -700, 0), (-100, 700, 30)),
                      part("RWG-001", "Rear wing", (-3900, 0, 30), (-3900, -500, 30), (-3400, 500, 950))],
            "mates": [{"a": "MON-001", "b": "FLR-001", "expect": "touching", "value_mm": 0},
                      {"a": "MON-001", "b": "FWG-001", "expect": "touching", "value_mm": 0},
                      {"a": "RWG-001", "b": "FLR-001", "expect": "gap", "value_mm": 50}],
            "assumptions": ["Concept proportions only"]}
    plan.update(over)
    return plan
