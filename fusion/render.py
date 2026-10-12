"""Render: a local photoreal render of a run's Fusion design per view, with the MCP screenshot as the fallback.

API (Fusion 2705.x, adsk/fusion.py stubs): Design.renderManager -> .sceneSettings (the document's SCENE SETTINGS),
.renderEnvironments (the Environment Library), .rendering (local / cloud render). Rendering.aspectRatio must be
CustomRenderAspectRatio BEFORE resolutionWidth / resolutionHeight are set, otherwise Fusion keeps the current aspect
ratio and changes the other side to match. Rendering.startLocalRender(filename, camera) starts a background render
process (queued, one at a time) and returns a RenderFuture: renderState (Queued / Processing / Finished / Failed),
progress 0..1, imageWidth / imageHeight, filename. There is no cancel call.

A render takes far longer than one MCP script call may (180 s client timeout), so it is three kinds of short scripts,
each ending normally with one @@RESULT@@ line:
    PREFLIGHT (read-only)  wrapper depth, the run's document found BY TAG, is it the active document, the
                           environment library names, the current scene settings
    START                  activate the run's document, aim the viewport with the view's screenshot camera, set the
                           render settings, startLocalRender, keep the RenderFuture in a module attribute
    POLL                   state + progress of that RenderFuture (once per minute)
Scene changes (camera, environment, background, light, ground) are made in the run's own unsaved document only;
application preferences are never touched; geometry is never touched.

Render camera (not the screenshot camera): the same view direction and up as the screenshot of that view, but framed
from the 8 corners of every part's measured world bbox so the car fills RENDER_FILL of the frame with an even margin
(fusion/render_frame.py). Perspective: SceneSettings.cameraFocalLength is set, the viewport camera's perspectiveAngle
is read back and matched to a 36 x 24 mm film axis (the API does not say which axis the angle spans), and the eye
distance follows from that angle. Orthographic: Camera.setExtents on a camera that is NOT assigned to the viewport
(a viewport recomputes one side from its own aspect ratio). The camera object is passed to startLocalRender.

Background: the chosen environment is set first (it lights the scene), then backgroundSolidColor, which switches the
background type to solid colour. Whether the environment keeps lighting the scene is verified live (the API cannot
read backgroundEnvironment back while the background is a solid colour).
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional

from fusion.assembly import _COMMON, VIEWS, _script
from fusion.client import FusionMCPClient
from fusion.render_frame import FRAME_HELPERS

# preset -> (quality, width, height); quality 25..100 (75 = Fusion's "Final")
PRESETS = {"draft": (25, 1280, 853), "standard": (50, 1920, 1280), "final": (75, 2400, 1600)}
CAMERAS = ("perspective", "orthographic")
MAX_LINE = 2500        # longest script line (chars) known to come back from Fusion; see start_script

_LOOKUP = r'''

def _find_by_tag():
    """(document, design) of the document carrying the run's tag; (None, None) if it is not open. Never by name."""
    app = adsk.core.Application.get()
    for i in range(app.documents.count):
        doc = app.documents.item(i)
        d = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
        a = d.attributes.itemByName(CFG["attr"][0], CFG["attr"][1]) if d else None
        if a is not None and a.value == CFG["doc_tag"]:
            return doc, d
    return None, None


def _jobs():
    jobs = getattr(adsk, "_agent_render_jobs", None)       # survives between script calls (same interpreter)
    if jobs is None:
        jobs = {}
        setattr(adsk, "_agent_render_jobs", jobs)
    return jobs


def _state(future):
    S = adsk.fusion.LocalRenderStates
    return {S.QueuedLocalRenderState: "queued", S.ProcessingLocalRenderState: "processing",
            S.FinishedLocalRenderState: "finished", S.FailedLocalRenderState: "failed"}.get(future.renderState,
                                                                                         str(future.renderState))


def _scene(rm):
    sc = rm.sceneSettings
    out = {}
    for k in ("cameraType", "cameraFocalLength", "backgroundType", "isGroundDisplayed", "isGroundReflections",
              "isGroundFlattened", "groundRoughness", "brightness", "lightAngle", "cameraExposure"):
        try:
            v = getattr(sc, k)
            out[k] = v if isinstance(v, (bool, int, float)) else str(v)
        except Exception as e:
            out[k] = "unreadable: %s" % type(e).__name__
    try:
        env = sc.backgroundEnvironment if sc.backgroundType == \
            adsk.fusion.RenderSceneBackgroundTypes.EnvironmentRenderSceneBackgroundType else None
        out["environment"] = env.name if env else None
    except Exception as e:
        out["environment"] = "unreadable: %s" % type(e).__name__
    try:
        if sc.backgroundType == adsk.fusion.RenderSceneBackgroundTypes.SolidColorRenderSceneBackgroundType:
            c = sc.backgroundSolidColor
            out["background"] = "#%02X%02X%02X" % (c.red, c.green, c.blue)
    except Exception as e:
        out["background"] = "unreadable: %s" % type(e).__name__
    return out
'''

_PREFLIGHT = _COMMON + _LOOKUP + r'''

def run(_context):
    res = {"ok": False, "depth": _depth()}
    try:
        app = adsk.core.Application.get()
        doc, design = _find_by_tag()
        res["found"] = doc is not None
        active = app.activeDocument
        ad = adsk.fusion.Design.cast(active.products.itemByProductType("DesignProductType")) if active else None
        aa = ad.attributes.itemByName(CFG["attr"][0], CFG["attr"][1]) if ad else None
        res["active_tag"] = aa.value if aa is not None else None
        res["documents"] = app.documents.count
        vp = app.activeViewport
        res["viewport"] = [vp.width, vp.height]
        cam = vp.camera
        e, t = cam.eye, cam.target
        res["camera"] = {"eye_cm": [round(e.x, 3), round(e.y, 3), round(e.z, 3)],
                         "target_cm": [round(t.x, 3), round(t.y, 3), round(t.z, 3)], "type": int(cam.cameraType)}
        if design is not None:
            rm = design.renderManager
            envs = rm.renderEnvironments
            res["environments"] = [envs.item(i).name for i in range(envs.count)]
            res["scene"] = _scene(rm)
        res["ok"] = True
    except Exception as e:
        res["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    print(CFG["marker"] + json.dumps(res))
'''

_START = _COMMON + FRAME_HELPERS + _LOOKUP + r'''
import os, time

def _clean_view(app, design):
    try:                                             # clean picture: no selection highlight, no joint glyphs
        app.userInterface.activeSelections.clear()
        design.rootComponent.isJointsFolderLightBulbOn = False
        for i in range(design.allComponents.count):
            c = design.allComponents.item(i)
            c.isSketchFolderLightBulbOn = False
            c.isConstructionFolderLightBulbOn = False
    except Exception:
        pass


def _p(v):
    return adsk.core.Point3D.create(v[0], v[1], v[2])


def _camera(app, design, sc, res):
    # the framed render camera (cm); returns the Camera object to pass to startLocalRender
    vp = app.activeViewport
    pts = [[x / 10.0, y / 10.0, z / 10.0] for lo, hi in CFG["boxes_mm"]              # 8 corners per part bbox
           for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    d, up, fill, aspect = CFG["dir"], CFG["up"], CFG["fill"], CFG["width"] / float(CFG["height"])
    cam = vp.camera
    cam.isSmoothTransition = False
    cam.isFitView = False
    cam.upVector = adsk.core.Vector3D.create(up[0], up[1], up[2])
    frame = {"mode": CFG["camera"], "viewport": [vp.width, vp.height]}     # the calibration may depend on it
    if CFG["camera"] == "perspective":
        sc.cameraType = adsk.core.CameraTypes.PerspectiveCameraType
        cam.cameraType = adsk.core.CameraTypes.PerspectiveCameraType
        vp.camera = cam
        sc.cameraFocalLength = CFG["focal_mm"]
        cam = vp.camera                                  # angle as Fusion derived it from the focal length
        angle = cam.perspectiveAngle
        axis, err = fov_axis(angle, CFG["focal_mm"])
        if err > 0.02:
            frame["note"] = "perspectiveAngle %.5f matches no 36x24 film axis for %s mm (best %s, %.1f%%): " \
                            "vertical assumed" % (angle, CFG["focal_mm"], axis, err * 100)
            axis = "vertical"
        th0, tv0 = half_tangents(angle, axis, aspect)
        # the distance and target of a TRUE focal_mm view (the uncorrected field): the perspective of that lens
        t, dist = frame_perspective(pts, d, up, th0, tv0, fill)
        p = fill_of(pts, t, d, up, dist, th0, tv0)
        sx, sy = CFG["field_scale"]                      # measured: the render shows a wider field (calibration)
        k = narrow_factor(p[:2], (sx, sy), fill) if (sx, sy) != (1.0, 1.0) else 1.0
        angle_set = narrowed_angle(angle, k)             # ... so the camera angle is narrowed, the eye stays put
        n = math.sqrt(sum(c * c for c in d))
        eye = [t[i] + d[i] / n * dist for i in range(3)]
        cam.isFitView = False
        cam.isSmoothTransition = False
        cam.target, cam.eye = _p(t), _p(eye)
        cam.upVector = adsk.core.Vector3D.create(up[0], up[1], up[2])
        cam.perspectiveAngle = angle_set
        vp.camera = cam                                  # the user sees what is rendered
        cam = vp.camera
        frame.update(angle=angle, axis=axis, axis_error=round(err, 5), distance_cm=round(dist, 3),
                     look_focal_mm=CFG["focal_mm"], field_scale=[sx, sy], narrow=round(k, 5),
                     angle_set=angle_set, nominal_focal_mm=round(focal_of(angle_set, axis), 2),
                     focal_read_back=sc.cameraFocalLength,
                     planned_fill_true_lens=[round(p[0], 4), round(p[1], 4)],
                     planned_fill=[round(p[0] * k / sx, 4), round(p[1] * k / sy, 4)],
                     planned_offset=[round(p[2], 4), round(p[3], 4)])
    else:
        sc.cameraType = adsk.core.CameraTypes.OrthographicCameraType
        t, w, h = frame_ortho(pts, d, up, aspect, fill)
        n = math.sqrt(sum(c * c for c in d))
        eye = [t[i] + d[i] / n * 800.0 for i in range(3)]
        cam.cameraType = adsk.core.CameraTypes.OrthographicCameraType
        cam.target, cam.eye = _p(t), _p(eye)
        cam.upVector = adsk.core.Vector3D.create(up[0], up[1], up[2])
        sx, sy = CFG["field_scale"]
        w, h = w / sx, h / sy                            # measured wider field -> smaller extents (calibration)
        ok = cam.setExtents(w, h)                        # NOT assigned to the viewport (it would change one side)
        frame.update(extents_cm=[round(w, 3), round(h, 3)], set_extents=bool(ok), field_scale=[sx, sy])
        try:
            got = cam.getExtents()
            frame["extents_read_back"] = [round(v, 3) for v in got[1:]] if isinstance(got, (list, tuple)) else str(got)
        except Exception as e:
            frame["extents_read_back"] = "unreadable: %s" % type(e).__name__
    e, tg = cam.eye, cam.target
    frame["eye_cm"] = [round(e.x, 3), round(e.y, 3), round(e.z, 3)]
    frame["target_cm"] = [round(tg.x, 3), round(tg.y, 3), round(tg.z, 3)]
    # live 2705.1.30: assigning a narrower perspectiveAngle made Fusion move the eye back by the tangent ratio
    frame["distance_read_back_cm"] = round(math.sqrt((e.x - tg.x) ** 2 + (e.y - tg.y) ** 2 + (e.z - tg.z) ** 2), 3)
    try:
        frame["angle_read_back"] = cam.perspectiveAngle if CFG["camera"] == "perspective" else None
    except Exception:
        pass
    res["frame"] = frame
    return cam


def _scene_set(rm, sc, res):
    if CFG.get("environment"):
        env = rm.renderEnvironments.itemByName(CFG["environment"])
        if env is None:
            raise ValueError("environment '%s' is not in the library" % CFG["environment"])
        sc.backgroundEnvironment = env                   # lights the scene ...
        res["environment_set"] = env.name
    bg = CFG["background_rgb"]
    sc.backgroundSolidColor = adsk.core.Color.create(bg[0], bg[1], bg[2], 255)     # ... background = solid colour
    sc.brightness = CFG["brightness_lux"]
    sc.lightAngle = math.radians(CFG["light_angle_deg"])
    sc.isGroundDisplayed = True
    sc.isGroundReflections = CFG["ground_reflections"]
    if CFG["ground_reflections"]:
        sc.groundRoughness = CFG["ground_roughness"]
    try:                                                 # documented as unreadable with a solid background
        res["environment_read_back"] = sc.backgroundEnvironment.name
    except Exception as e:
        res["environment_read_back"] = "unreadable with a solid background (%s)" % type(e).__name__


def run(_context):
    res = {"ok": False, "depth": _depth(), "started": False}
    if res["depth"] > CFG["max_depth"]:
        res["error"] = "MCP stdout wrapper depth %d > %d: restart Fusion first" % (res["depth"], CFG["max_depth"])
        print(CFG["marker"] + json.dumps(res))
        return
    try:
        app = adsk.core.Application.get()
        design = _design()                               # by tag; activates the run's document
        _clean_view(app, design)
        rm = design.renderManager
        sc = rm.sceneSettings
        res["scene_before"] = _scene(rm)
        _scene_set(rm, sc, res)
        cam = _camera(app, design, sc, res)
        res["scene"] = _scene(rm)
        if CFG.get("aim_only"):                          # re-calibration: the camera only, no render
            res["ok"] = True
            print(CFG["marker"] + json.dumps(res))
            return
        r = rm.rendering
        r.aspectRatio = adsk.fusion.RenderAspectRatios.CustomRenderAspectRatio     # before the resolution
        r.resolutionWidth = CFG["width"]
        r.resolutionHeight = CFG["height"]
        r.renderQuality = CFG["quality"]
        r.isBackgroundTransparent = False
        res["settings"] = {"aspect_custom": r.aspectRatio == adsk.fusion.RenderAspectRatios.CustomRenderAspectRatio,
                           "width": r.resolutionWidth, "height": r.resolutionHeight, "quality": r.renderQuality}
        if os.path.exists(CFG["path"]):
            os.remove(CFG["path"])
        future = r.startLocalRender(CFG["path"], cam)
        if future is None:
            res["error"] = "startLocalRender returned no RenderFuture (render refused)"
        else:
            _jobs()[CFG["token"]] = future
            res.update(started=True, state=_state(future), progress=future.progress,
                       image=[future.imageWidth, future.imageHeight], filename=future.filename)
            res["ok"] = True
    except Exception as e:
        res["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    print(CFG["marker"] + json.dumps(res))
'''

_POLL = _COMMON + _LOOKUP + r'''

def run(_context):
    res = {"ok": False, "depth": _depth()}
    try:
        future = _jobs().get(CFG["token"])
        res["known"] = future is not None
        if future is not None:
            res.update(state=_state(future), progress=future.progress, image=[future.imageWidth, future.imageHeight])
        res["ok"] = True
    except Exception as e:
        res["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    print(CFG["marker"] + json.dumps(res))
'''


def preflight_script(doc_tag: str) -> str:
    return _script(_PREFLIGHT, {"doc_tag": doc_tag, "render_preflight": True})


class ScriptTooLong(ValueError):
    """A script line longer than MAX_LINE: Fusion has returned such scripts as success with empty output, unrun."""


def start_script(doc_tag: str, view: str, boxes_mm: list, path: str, token: str, opts: dict, max_depth: int,
                 field_scale=(1.0, 1.0), aim_only: bool = False) -> str:
    """opts: a validated agent.render_run.RenderOptions.cfg() (preset, camera, focal_mm, background, light, ground);
    boxes_mm: the parts' measured world bboxes [[min], [max]] (the framing input; the script uses their corners).
    Sent rounded to 0.1 mm as boxes, not corners: the CFG is one base64 line, and a start script with a 5.8 KB line
    (144 corners) came back from Fusion as success with empty output, three times, without running (live, 2705.1.30).
    The longest line is kept below MAX_LINE (the assembly script's 2.2 KB line works live)."""
    if opts["preset"] not in PRESETS or opts["camera"] not in CAMERAS:
        raise ValueError(f"bad render options {opts}")
    quality, width, height = PRESETS[opts["preset"]]
    if opts.get("size"):                                 # custom size, 108..4000 px per side (API limit)
        width, height = (int(v) for v in opts["size"])
    d, up = VIEWS[view]
    s = _script(_START, dict(opts, doc_tag=doc_tag, render_start=True, view=view, path=str(path), token=token,
                             quality=quality, width=width, height=height, max_depth=int(max_depth),
                             dir=list(d), up=list(up), field_scale=[float(v) for v in field_scale],
                             aim_only=bool(aim_only),
                             boxes_mm=[[[round(float(v), 1) for v in c] for c in b] for b in boxes_mm]))
    longest = max(len(ln) for ln in s.splitlines())
    if longest > MAX_LINE:
        raise ScriptTooLong(f"render start script line of {longest} chars > {MAX_LINE}: not sent (Fusion returns "
                            f"such scripts as success with empty output, unrun)")
    return s


def poll_script(doc_tag: str, token: str) -> str:
    return _script(_POLL, {"doc_tag": doc_tag, "render_poll": True, "token": token})


def preflight(client: FusionMCPClient, doc_tag: str) -> dict:
    return client.run_script(preflight_script(doc_tag), read_only=True).data or {}


def png_size(path: Path) -> Optional[tuple[int, int]]:
    """(width, height) from a PNG's IHDR chunk; None if the file is not a PNG."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])
