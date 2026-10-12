"""Fast-mode configuration (tolerances and budgets). Override any value with env FAST_<NAME>, e.g. FAST_BBOX_TOL_MM=10."""
from __future__ import annotations

import os

_DEFAULTS = {
    "BBOX_TOL_MM": 5.0,            # measured world bbox may exceed the planned envelope by this much per side
    "TOUCH_TOL_MM": 0.5,           # |gap| <= this counts as touching
    "OVERLAP_IGNORE_MM3": 1.0,     # interference volumes below this are numerical noise
    "PAIR_NEAR_MM": 10.0,
    "DEPTH_RAY_GRID": 9,           # n x n rays per interference piece for the overlap depth (MEASURE_VERSION 2)          # unmated part pairs whose bboxes are farther apart are not measured
    "SCRIPT_CALL_BUDGET": 35,      # Fusion script calls per design run (MCP add-in stdout wrapper leak)
    "MAX_REPAIRS": 2,              # Claude repair calls per part
    "MAX_FIA_SNIPPETS": 6,
    "FIA_SNIPPET_CHARS": 400,
    "CLAUDE_TIMEOUT_S": 900,
    "REVISE_SCRIPT_BUDGET": 10,    # Fusion script calls per revision step (addendum E), rollback reserved inside it
    "REVISE_MAX_DEPTH": 100,       # refuse to start a revision above this MCP stdout wrapper depth
    "DERIVED_VOLUME_REL": 1e-6,    # derived (mirror / yaw180) part volume vs its source, relative
    "DERIVED_BBOX_TOL_MM": 0.01,   # derived local bbox vs the source's (mirrored / equal)
    "DERIVED_WORLD_TOL_MM": 0.5,   # derived world bbox vs the source's mirrored about Y = 0
    "RENDER_MAX_DEPTH": 100,       # refuse to start a render above this MCP stdout wrapper depth
    "RENDER_PRESET": "standard",   # draft (25, 1280x853) | standard (50, 1920x1280) | final (75, 2400x1600)
    "RENDER_CAMERA": "perspective",  # or orthographic
    "RENDER_FOCAL_MM": 50.0,       # perspective focal length, 35..85 mm
    "RENDER_FILL": 0.8,            # the car's larger relative side fills this much of the frame
    "RENDER_BACKGROUND": "#3A3F47",  # solid render background (anthracite); the environment still lights the scene
    "RENDER_BRIGHTNESS_LUX": 1000.0,  # SceneSettings.brightness, 0..100000 lux
    "RENDER_LIGHT_ANGLE_DEG": 30.0,  # SceneSettings.lightAngle (environment rotation), -180..180
    "RENDER_GROUND_ROUGHNESS": 0.15,  # ground reflections on by default; 0 = mirror, 1 = rough
    "RENDER_TIMEOUT_S": 900,       # per view; then the screenshot fallback
    "RENDER_POLL_S": 60,           # one state check (1 script call) per this many seconds
    "RENDER_FALLBACK_WIDTH": 2400,  # MCP screenshot used when a render is refused, fails or times out
    "RENDER_FALLBACK_HEIGHT": 1600,
}


def get(name: str):
    default = _DEFAULTS[name]
    raw = os.environ.get(f"FAST_{name}")
    if raw is None:
        return default
    return type(default)(raw)

