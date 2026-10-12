"""Live test of the Claude Code reasoning backend (python -m pytest -m claude).

Sends a real MVP 1.1 review task (from the committed BRK-002 run) through `claude -p` and checks that the
structured output validates against the engine's ReviewResponse schema. Uses the local Claude Code login.
"""
import json
from pathlib import Path

import pytest

from agent.reasoning import ClaudeCodeBackend, ReasoningTask, ReviewResponse

pytestmark = pytest.mark.claude
TASK = Path(__file__).resolve().parents[2] / \
    "data/prototype_bench/runs/20261005-205141-design-a-machined-alumin/reasoning/06_review.request.json"


def test_claude_code_backend_returns_schema_valid_review(tmp_path):
    ok, detail = ClaudeCodeBackend.available()
    if not ok:
        pytest.skip(detail)
    task = ReasoningTask.model_validate(json.loads(TASK.read_text(encoding="utf-8")))
    out = ClaudeCodeBackend(tmp_path).request(task)
    review = ReviewResponse.model_validate(out)
    assert review.decision in ("ACCEPT", "REVISE", "STOP") and review.rationale
    meta = json.loads((tmp_path / "reasoning" / f"{task.stem}.meta.json").read_text(encoding="utf-8"))
    assert meta["answered_by"] == "claude_code" and meta["models"]


def test_claude_code_reads_attached_image_as_image_evidence(tmp_path):
    """Real analysis task with an attached drawing: Claude Code must see the image, and the engine's gates must
    accept the result with the drawing's values recorded as IMAGE evidence (not as user words)."""
    ok, detail = ClaudeCodeBackend.available()
    if not ok:
        pytest.skip(detail)
    import io
    from PIL import Image, ImageDraw, ImageFont
    from agent.workflow import Engine, create_run
    from tests.helpers import FakeFusion
    from vehicle.store import ProjectStore
    im = Image.new("RGB", (700, 420), "white")
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except OSError:
        font = ImageFont.load_default()
    d.rectangle([100, 90, 600, 330], outline="black", width=4)                 # upright leg face
    d.ellipse([215, 190, 245, 220], outline="black", width=3)
    d.ellipse([455, 190, 485, 220], outline="black", width=3)
    d.line([230, 260, 470, 260], fill="black", width=2)
    d.text((300, 268), "40 mm", fill="black", font=font)
    d.text((110, 30), "SENSOR BOX MOUNT - UPRIGHT LEG: 2x M5 CLEARANCE HOLES", fill="black", font=font)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    store = ProjectStore("bench", root=tmp_path)
    eng = Engine(store, backend_factory=lambda run: ClaudeCodeBackend(run.dir), fusion=FakeFusion())
    run = create_run(store, "Design a machined aluminium L-bracket for the sensor box shown in the attached sketch; "
                            "the base is bolted to a flat plate with four M6 bolts.", images=[(buf.getvalue(), "sketch.png")])
    run = eng.advance(run)                         # analysis only; stops at questions or at the plan request
    assert run["analysis"] is not None, run["events"]
    image_reqs = [r for r in run["analysis"]["requirements"] if r["source"] == "IMAGE"]
    assert image_reqs and all(r["attachment_id"] == "IMG-01" for r in image_reqs)
    assert not any(r["source"] == "USER_ANSWER" for r in run["analysis"]["requirements"])
    meta = json.loads((run.dir / "reasoning" / "01_analysis.meta.json").read_text(encoding="utf-8"))
    assert meta["attachments_sent"] == ["IMG-01"]
