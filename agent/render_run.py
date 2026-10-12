"""Render a finished run's Fusion design (zero Claude calls, no geometry change, no registry write).

    PREFLIGHT  1 read-only script: wrapper depth, the run's document found by its tag, environment library names.
               Refused (nothing rendered, nothing shot) above RENDER_MAX_DEPTH or when the document is not open.
    per view   START (1 script) -> POLL once per RENDER_POLL_S (1 script each) until finished / failed / timeout
               (RENDER_TIMEOUT_S per view). Refused, failed or timed out -> the MCP screenshot at
               RENDER_FALLBACK_WIDTH x HEIGHT (1 camera script + 1 screenshot), recorded with the reason.

Options (RenderOptions): preset draft | standard | final, camera perspective (focal 35..85 mm) | orthographic framed
from the parts' measured world bboxes, solid background colour, environment (lighting only; a library name), brightness,
light angle, ground reflections + roughness. Defaults in agent/fast_config.py (RENDER_*).

Fusion writes the render to an ASCII temp path (tempfile.gettempdir()/agent_renders); the finished file is copied to
<run>/renders/<RDnn>/<view>.png. Recorded as run["renders"][n] (RDnn); every item carries view, path, size_bytes,
width, height, quality, seconds, method (render | screenshot_fallback | none), state, progress and any note / error.
run.json is saved after every state change, so the UI shows queued / processing (progress) / finished live.
"""
from __future__ import annotations

import re
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

from agent import fast_config
from fusion.assembly import camera_script
from fusion.client import FusionError, FusionOutputLost
from fusion import render_calibration
from fusion.render import CAMERAS, PRESETS, ScriptTooLong, png_size, poll_script, preflight, start_script
from vehicle.models import now_iso

VIEWS = ("iso", "front", "top")


def temp_render_dir() -> Path:
    return Path(tempfile.gettempdir()) / "agent_renders"


HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class RenderOptions:
    preset: str
    camera: str
    focal_mm: float
    background: str
    environment: Optional[str]
    brightness_lux: float
    light_angle_deg: float
    ground_reflections: bool
    ground_roughness: float
    fill: float
    size: Optional[tuple] = None          # custom render size (w, h), 108..4000 px (API limit); else the preset's
    crop: bool = True                     # crop the finished render around the car (fusion/render_crop.py)
    crop_output: Optional[tuple] = None   # crop target size; else the preset's resolution

    @property
    def quality(self) -> int:
        return PRESETS[self.preset][0]

    @property
    def resolution(self) -> list:
        return list(self.size) if self.size else list(PRESETS[self.preset][1:])

    @property
    def crop_target(self) -> list:
        return list(self.crop_output) if self.crop_output else list(PRESETS[self.preset][1:])

    def cfg(self) -> dict:
        h = self.background
        return dict(asdict(self), background_rgb=[int(h[i:i + 2], 16) for i in (1, 3, 5)])


RENDER_MIN_PX, RENDER_MAX_PX = 108, 4000    # Rendering.resolutionWidth / resolutionHeight (API docs)


def _size(raw, name, lo, hi):
    if raw in (None, ""):
        return None
    try:
        if isinstance(raw, str):
            raw = raw.lower().split("x")
        w, h = (int(v) for v in raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be WIDTHxHEIGHT") from None
    if not (lo <= w <= hi and lo <= h <= hi):
        raise ValueError(f"{name} {w}x{h}: each side must be between {lo} and {hi} px")
    return (w, h)


def _num(raw, name, lo, hi, default):
    if raw is None or raw == "":
        return float(default)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not lo <= v <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}")
    return v


def parse_options(raw: Optional[dict] = None, known_environments: Optional[list] = None) -> RenderOptions:
    """Validated render options; missing keys take the RENDER_* defaults. A legacy quality 50 / 75 maps to the
    standard / final preset."""
    raw = dict(raw or {})
    preset = raw.get("preset")
    if preset is None and raw.get("quality") is not None:
        preset = {50: "standard", 75: "final", 25: "draft"}.get(_int(raw["quality"]))
        if preset is None:
            raise ValueError(f"quality must be one of 25, 50, 75 (or use preset {', '.join(PRESETS)})")
    preset = preset or fast_config.get("RENDER_PRESET")
    if preset not in PRESETS:
        raise ValueError(f"preset must be one of {', '.join(PRESETS)}")
    camera = raw.get("camera") or fast_config.get("RENDER_CAMERA")
    if camera not in CAMERAS:
        raise ValueError(f"camera must be one of {', '.join(CAMERAS)}")
    bg = (raw.get("background") or fast_config.get("RENDER_BACKGROUND")).strip()
    if not HEX_RE.match(bg):
        raise ValueError("background must be a #RRGGBB colour")
    env = (raw.get("environment") or "").strip() or None
    if env is not None and known_environments is not None and env not in known_environments:
        raise ValueError(f"environment '{env}' is not in the Fusion library list")
    if env is not None and env.endswith("..."):
        raise ValueError(f"'{env}' is a library placeholder, not an environment")
    refl = raw.get("ground_reflections")
    refl = True if refl is None else refl
    if not isinstance(refl, bool):
        raise ValueError("ground_reflections must be true or false")
    return RenderOptions(
        preset=preset, camera=camera,
        focal_mm=_num(raw.get("focal_mm"), "focal_mm", 35, 85, fast_config.get("RENDER_FOCAL_MM")),
        background=bg.upper(), environment=env,
        brightness_lux=_num(raw.get("brightness_lux"), "brightness_lux", 0, 100000,
                            fast_config.get("RENDER_BRIGHTNESS_LUX")),
        light_angle_deg=_num(raw.get("light_angle_deg"), "light_angle_deg", -180, 180,
                             fast_config.get("RENDER_LIGHT_ANGLE_DEG")),
        ground_reflections=refl,
        ground_roughness=_num(raw.get("ground_roughness"), "ground_roughness", 0, 1,
                              fast_config.get("RENDER_GROUND_ROUGHNESS")),
        fill=_num(raw.get("fill"), "fill", 0.3, 0.95, fast_config.get("RENDER_FILL")),
        size=_size(raw.get("size"), "size", RENDER_MIN_PX, RENDER_MAX_PX),
        crop=_bool(raw.get("crop"), "crop", True),
        crop_output=_size(raw.get("crop_output"), "crop_output", 16, 20000))


def _bool(raw, name, default):
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise ValueError(f"{name} must be true or false")
    return raw


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def validate_views(views) -> list:
    views = list(views or ["iso"])
    if not views or any(v not in VIEWS for v in views) or len(set(views)) != len(views):
        raise ValueError(f"views must be distinct values of {', '.join(VIEWS)}")
    return [v for v in VIEWS if v in views]


def bbox_boxes(run) -> list:
    """Every built part's measured world bbox [[min], [max]] (mm): the render framing input (the script uses the 8
    corners of each)."""
    return [st["bbox"] for st in run["parts"].values() if st.get("state") == "done" and st.get("bbox")]


class RenderRunner:
    def __init__(self, orch, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.orch, self.sleep, self.clock = orch, sleep, clock

    def run(self, run, views=("iso",), options=None) -> dict:
        if run["status"] not in ("DONE", "FAILED"):
            raise ValueError(f"the run is {run['status']}; render a finished run")
        if not self.orch.built_ids(run):
            raise ValueError("the run has no built parts")
        views = validate_views(views)
        opts = options if isinstance(options, RenderOptions) else parse_options(options)
        recs = run.data.setdefault("renders", [])
        rd = {"id": f"RD{len(recs) + 1:02d}", "created": now_iso(), "finished": None, "status": "running",
              "views": views, "preset": opts.preset, "quality": opts.quality, "environment": opts.environment,
              "resolution": opts.resolution, "options": asdict(opts),
              "timeout_s": fast_config.get("RENDER_TIMEOUT_S"), "doc_tag": run["doc_tag"], "preflight": None,
              "items": [{"view": v, "state": "pending", "progress": 0.0, "method": None, "path": None,
                         "size_bytes": None, "width": None, "height": None, "quality": opts.quality,
                         "seconds": None, "note": None, "error": None} for v in views],
              "script_calls": 0, "depth_first": None, "depth_last": None, "error": None, "seconds": None}
        recs.append(rd)
        self._opts = opts
        run.log(f"{rd['id']}: render {', '.join(views)} ({opts.preset}, {opts.camera}"
                f"{f' {opts.focal_mm:g} mm' if opts.camera == 'perspective' else ''}"
                f"{', ' + opts.environment if opts.environment else ''}) requested")
        run.save()
        t0 = self.clock()
        try:
            self._render(run, rd)
        except FusionError as e:                         # preflight or a call outside an item: never silent
            rd["error"] = f"Fusion: {e}"
            rd["status"] = "failed"
        rd["seconds"] = round(self.clock() - t0, 1)
        rd["finished"] = now_iso()
        if rd["status"] == "running":
            rd["status"] = "done"
        run.log(f"{rd['id']}: {summary(rd)} ({rd['script_calls']} script call(s))")
        run.save()
        return rd

    # ------------------------------------------------------------------ steps
    def _calls(self, run, rd: dict, n: int, depth: Optional[int]) -> None:
        rd["script_calls"] += n
        if depth is not None:
            rd["depth_first"] = depth if rd["depth_first"] is None else rd["depth_first"]
            rd["depth_last"] = depth
        self.orch._script_calls(run, n, depth)

    def _render(self, run, rd: dict) -> None:
        fusion = self.orch.fusion()
        pf = preflight(fusion, run["doc_tag"])
        self._calls(run, rd, 1, pf.get("depth"))
        rd["preflight"] = {k: pf.get(k) for k in ("depth", "found", "active_tag", "documents", "environments",
                                                   "scene", "viewport", "camera", "error")}
        rd["camera_moved"] = camera_moved(run, rd, pf.get("camera"))
        if rd["camera_moved"]:
            run.log(f"{rd['id']}: the viewport camera moved since {rd['camera_moved']['since']} "
                    f"(eye moved {rd['camera_moved']['eye_moved_cm']} cm) - not by this pipeline")
        rd["preflight"]["active_is_run_document"] = pf.get("active_tag") == run["doc_tag"]
        limit = fast_config.get("RENDER_MAX_DEPTH")
        if not pf.get("ok"):
            return self._refuse(run, rd, f"preflight failed: {pf.get('error') or 'no result'}")
        if pf.get("depth") is not None and pf["depth"] > limit:
            return self._refuse(run, rd, f"MCP stdout wrapper depth is {pf['depth']} (> {limit}): restart Fusion "
                                         f"before rendering")
        if not pf.get("found"):
            return self._refuse(run, rd, f"the run's design document (tag {run['doc_tag']}) is not open in Fusion")
        if rd["environment"] and rd["environment"] not in (pf.get("environments") or []):
            return self._refuse(run, rd, f"environment '{rd['environment']}' is not in the Fusion library")
        run.save()
        for item in rd["items"]:
            try:
                self._view(run, rd, item)
            except FusionOutputLost as e:                # the channel is gone: no further view can work
                item["error"] = (item["error"] + "; " if item["error"] else "") + f"Fusion: {e}"
                item["state"] = "failed"
                limit, depth = fast_config.get("RENDER_MAX_DEPTH"), rd.get("depth_last")
                if depth is not None and depth <= limit:
                    rd["error"] = (f"Fusion returned no result at wrapper depth {depth} (limit {limit}): the script "
                                   f"probably did not run; the channel is not exhausted, so check the script before "
                                   f"restarting Fusion ({e})")
                else:
                    rd["error"] = f"Fusion output lost ({e}); restart Fusion"
                rd["status"] = "failed"
                for rest in rd["items"]:
                    if rest["state"] == "pending":
                        rest.update(state="skipped", error="not attempted: Fusion output lost")
                run.save()
                return
            run.save()

    def _refuse(self, run, rd: dict, why: str) -> None:
        rd.update(status="refused", error=why)
        for item in rd["items"]:
            item.update(state="refused", error=why)

    def _view(self, run, rd: dict, item: dict) -> None:
        view = item["view"]
        out_dir = run.dir / "renders" / rd["id"]
        tmp = temp_render_dir() / f"{run.id}_{rd['id']}_{view}.png"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        if tmp.exists():
            tmp.unlink()
        token = f"{run.id}/{rd['id']}/{view}"
        w, h = rd["resolution"]
        t0 = self.clock()
        item["state"] = "starting"
        run.save()
        cal = render_calibration.field_scale(self._opts.camera, w, h, (rd.get("preflight") or {}).get("viewport"))
        notes = []
        if cal is not None and not cal["viewport_match"]:
            cal = self._recalibrate(run, rd, item, cal, notes)
        item["calibration"] = cal
        try:
            script = start_script(run["doc_tag"], view, bbox_boxes(run), str(tmp), token, self._opts.cfg(),
                                  fast_config.get("RENDER_MAX_DEPTH"), cal["scale"] if cal else (1.0, 1.0))
        except ScriptTooLong as e:                       # never sent: Fusion would "succeed" without running it
            return self._fallback(run, rd, item, f"render not started: {e}", t0, notes)
        r = None
        try:
            r = self.orch.fusion().run_script(script).data or {}
        except FusionOutputLost:
            self._calls(run, rd, 1, None)               # the call was made, even though nothing came back
            raise
        except FusionError as e:
            r = {"ok": False, "error": f"Fusion: {e}"}
        self._calls(run, rd, 1, r.get("depth"))
        item["settings"] = r.get("settings")
        item["scene"] = r.get("scene")
        item["frame"] = r.get("frame")
        item["environment_read_back"] = r.get("environment_read_back")
        if not r.get("ok") or not r.get("started"):
            return self._fallback(run, rd, item, f"render refused: {r.get('error') or 'no result'}", t0, notes)
        self._set_state(item, r)
        s = r.get("settings") or {}
        fr = r.get("frame") or {}
        if fr.get("note"):
            notes.append(fr["note"])
        nf = fr.get("nominal_focal_mm")
        dset, dgot = fr.get("distance_cm"), fr.get("distance_read_back_cm")
        moved = dset is not None and dgot is not None and abs(dgot - dset) > 0.01 * dset
        if moved:
            notes.append(f"Fusion moved the eye: distance set {dset} cm, read back {dgot} cm "
                         f"(x{dgot / dset:.4f}); the perspective is NOT that of a {fr.get('look_focal_mm')} mm lens "
                         f"at {dset} cm")
        if nf is not None and not 35.0 <= nf <= 85.0 and not moved:
            notes.append(f"the narrowed camera angle corresponds to a nominal {nf:g} mm focal length (outside 35-85; "
                         f"Fusion's scene focal length reads {fr.get('focal_read_back')}); the perspective is that of "
                         f"a {fr.get('look_focal_mm')} mm lens at {fr.get('distance_cm')} cm")
        if cal is None:
            notes.append(f"framing uncalibrated for {self._opts.camera} at {w}x{h}: the car will likely be smaller "
                         f"than planned (fusion/render_calibration.json has no entry)")
        if (s.get("width"), s.get("height")) != (w, h) or not s.get("aspect_custom"):
            notes.append(f"Fusion read back {s.get('width')}x{s.get('height')} (custom aspect "
                         f"{s.get('aspect_custom')}), requested {w}x{h}")
        if s.get("quality") != rd["quality"]:
            notes.append(f"Fusion read back quality {s.get('quality')}, requested {rd['quality']}")
        run.save()
        timeout, poll = fast_config.get("RENDER_TIMEOUT_S"), fast_config.get("RENDER_POLL_S")
        while True:
            if item["state"] == "finished" or (item.get("_lost_future") and _ready(tmp)):
                if not _ready(tmp):
                    return self._fallback(run, rd, item, f"Fusion reported the render finished but wrote no PNG "
                                                         f"at {tmp}", t0, notes)
                out_dir.mkdir(parents=True, exist_ok=True)
                dest = out_dir / f"{view}.png"
                shutil.copyfile(tmp, dest)
                size = png_size(dest)
                item.update(state="finished", progress=1.0, method="render",
                            path=dest.relative_to(run.dir).as_posix(), size_bytes=dest.stat().st_size,
                            width=size[0] if size else None, height=size[1] if size else None,
                            seconds=round(self.clock() - t0, 1),
                            render_full=dest.relative_to(run.dir).as_posix(), render_cropped=None, crop=None)
                item.pop("_lost_future", None)
                if self._opts.crop:
                    self._crop(run, item, dest, notes)
                item["note"] = "; ".join(notes) or None
                return
            if item["state"] == "failed":
                return self._fallback(run, rd, item, "Fusion reported the render as failed", t0, notes)
            if self.clock() - t0 >= timeout:
                notes.append("the render may still be running in Fusion (there is no cancel call)")
                return self._fallback(run, rd, item, f"render timed out after {timeout} s "
                                                     f"(last state {item['state']}, progress {item['progress']:.0%})",
                                      t0, notes)
            self.sleep(poll)
            try:
                p = self.orch.fusion().run_script(poll_script(run["doc_tag"], token)).data or {}
            except FusionOutputLost:
                self._calls(run, rd, 1, None)
                raise
            except FusionError as e:
                p = {"ok": False, "error": f"Fusion: {e}"}
            self._calls(run, rd, 1, p.get("depth"))
            if p.get("ok") and p.get("known"):
                self._set_state(item, p)
            elif p.get("ok"):                            # the RenderFuture was lost (add-in reloaded): watch the file
                item["_lost_future"] = True
                notes.append("RenderFuture no longer known to Fusion; completion taken from the output file")
                notes[:] = list(dict.fromkeys(notes))
            else:
                notes.append(f"state check failed: {p.get('error')}")
            run.save()

    def _crop(self, run, item: dict, full: Path, notes: list) -> None:
        """PIL crop around the measured car (zero Fusion calls); the cropped image becomes the item's main path."""
        from fusion.render_crop import crop_render
        dst = full.with_name(f"{item['view']}_cropped.png")
        try:
            c = crop_render(full, dst, fill=self._opts.fill, aspect=1.5, target=self._opts.crop_target)
        except Exception as e:                           # never silent: the full render stays the result
            c = {"skipped": f"crop failed: {type(e).__name__}: {e}"}
        item["crop"] = c
        if c.get("skipped"):
            notes.append(f"not cropped: {c['skipped']}")
            return
        item["render_cropped"] = dst.relative_to(run.dir).as_posix()
        item.update(path=item["render_cropped"], size_bytes=dst.stat().st_size,
                    width=c["output_size"][0], height=c["output_size"][1],
                    native_size=c["native_size"])
        fs = png_size(full)
        item["full_size"] = list(fs) if fs else None
        if c.get("note"):
            notes.append(c["note"])
        if any(c["padded"]):
            notes.append(f"crop padded with the background colour {c['padded']} px (left, top, right, bottom)")
        if c["car_touches_edge"]:
            notes.append("the car touches the edge of the full render: it may be cut off")

    def _recalibrate(self, run, rd: dict, item: dict, cal: dict, notes: list) -> Optional[dict]:
        """The viewport differs from the calibration's: aim the uncorrected (true-lens) camera, take a screenshot at
        the render size, measure its fill and re-scale the render factor by screenshot factor now / at calibration.
        Never silent: the note says the calibration may not apply and how it was re-scaled (or that it was not)."""
        from fusion.render_measure import measure_fill
        w, h = rd["resolution"]
        head = (f"calibration may not apply: viewport changed (calibrated at {cal['viewport']}, now "
                f"{cal['viewport_now']})")
        fusion = self.orch.fusion()
        try:
            a = fusion.run_script(start_script(run["doc_tag"], item["view"], bbox_boxes(run), "", "aim",
                                               self._opts.cfg(), fast_config.get("RENDER_MAX_DEPTH"),
                                               aim_only=True)).data or {}
        except FusionOutputLost:
            self._calls(run, rd, 1, None)
            raise
        except FusionError as e:
            a = {"ok": False, "error": str(e)}
        self._calls(run, rd, 1, a.get("depth"))
        planned = ((a.get("frame") or {}).get("planned_fill_true_lens")) if a.get("ok") else None
        m = None
        if planned and cal.get("screenshot_scale"):
            try:
                m = measure_fill(fusion.screenshot(direction="current", width=w, height=h))
            except Exception as e:
                notes.append(f"{head}; re-calibration screenshot failed ({e}): framing UNCORRECTED")
                return None
        if not m or not planned:
            notes.append(f"{head}; re-calibration not possible "
                         f"({a.get('error') or 'no screenshot measurement'}): framing UNCORRECTED")
            return None
        now = [round(planned[i] / m["fill"][i], 4) for i in range(2)]
        scale = render_calibration.rescale(cal, now)
        notes.append(f"{head}; re-scaled from a screenshot measurement (screenshot factor {cal['screenshot_scale']} "
                     f"at calibration, {now} now): factor {cal['scale']} -> {scale}, UNVERIFIED")
        return dict(cal, scale=scale, recalibrated={"screenshot_fill": m["fill"], "screenshot_scale": now})

    @staticmethod
    def _set_state(item: dict, r: dict) -> None:
        item["state"] = r.get("state") or item["state"]
        try:
            item["progress"] = round(float(r.get("progress") or 0.0), 3)
        except (TypeError, ValueError):
            pass

    def _fallback(self, run, rd: dict, item: dict, why: str, t0: float, notes: Optional[list] = None) -> None:
        """The MCP screenshot of the same view (same camera script as the run's screenshots), recorded with why."""
        item.pop("_lost_future", None)
        item["error"] = why
        fw, fh = fast_config.get("RENDER_FALLBACK_WIDTH"), fast_config.get("RENDER_FALLBACK_HEIGHT")
        fusion = self.orch.fusion()
        try:
            c = fusion.run_script(camera_script(run["doc_tag"], item["view"], self.orch._center(run))).data or {}
        except FusionOutputLost:
            self._calls(run, rd, 1, None)
            raise
        except FusionError as e:
            c = {"ok": False, "error": f"Fusion: {e}"}
        self._calls(run, rd, 1, c.get("depth"))
        png = None
        if c.get("ok"):
            try:
                png = fusion.screenshot(direction="current", width=fw, height=fh)
            except Exception as e:                       # reported, never silent
                why = f"{why}; screenshot fallback failed: {e}"
        else:
            why = f"{why}; screenshot fallback camera failed: {c.get('error')}"
        if png is None:
            item.update(state="failed", method="none", error=why, seconds=round(self.clock() - t0, 1),
                        note="; ".join(notes or []) or None)
            return
        out_dir = run.dir / "renders" / rd["id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{item['view']}.png"
        dest.write_bytes(png)
        size = png_size(dest)
        item.update(state="fallback", method="screenshot_fallback", path=dest.relative_to(run.dir).as_posix(),
                    size_bytes=len(png), width=size[0] if size else fw, height=size[1] if size else fh,
                    seconds=round(self.clock() - t0, 1),
                    note="; ".join((notes or []) + [f"NOT a render: MCP screenshot {fw}x{fh} (fallback)"]))


def camera_moved(run, rd: dict, cam_now: Optional[dict], tol_cm: float = 0.5) -> Optional[dict]:
    """The viewport camera at preflight vs the camera the previous render of this run set (the pipeline leaves it
    there): a difference means someone or something else moved the view between renders."""
    if not cam_now:
        return None
    for prev in reversed(run.data.get("renders") or []):
        if prev is rd:
            continue
        fr = next((i.get("frame") for i in reversed(prev.get("items", [])) if i.get("frame")
                   and i["frame"].get("eye_cm")), None)
        if fr:
            de = sum((a - b) ** 2 for a, b in zip(fr["eye_cm"], cam_now["eye_cm"])) ** 0.5
            dt = sum((a - b) ** 2 for a, b in zip(fr["target_cm"], cam_now["target_cm"])) ** 0.5
            if de > tol_cm or dt > tol_cm:
                return {"since": prev["id"], "eye_moved_cm": round(de, 2), "target_moved_cm": round(dt, 2)}
            return None
    return None


def _ready(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0 and png_size(path) is not None


def summary(rd: dict) -> str:
    if rd["status"] == "refused":
        return f"render refused: {rd['error']}"
    parts = []
    for it in rd["items"]:
        if it["method"] == "render" and it.get("render_cropped"):
            fs = it.get("full_size") or ["?", "?"]
            parts.append(f"{it['view']} rendered ({fs[0]}x{fs[1]}, {it['seconds']} s), cropped to "
                         f"{it['width']}x{it['height']}")
        elif it["method"] == "render":
            parts.append(f"{it['view']} rendered ({it['width']}x{it['height']}, {it['seconds']} s)")
        elif it["method"] == "screenshot_fallback":
            parts.append(f"{it['view']} SCREENSHOT FALLBACK ({it['error']})")
        else:
            parts.append(f"{it['view']} {it['state']}: {it['error']}")
    return "; ".join(parts) + (f"; {rd['error']}" if rd.get("error") else "")
