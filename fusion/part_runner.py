"""Free-form part runner: validate a body, compose it with the prelude, run it (ONE script call: build + place +
measure), check it, and produce a registry record. Also `rebuild_part`: re-run a registered part's stored script with
zero Claude calls."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from fusion.client import FusionMCPClient
from fusion.prelude import compose_part_script, param_prefix, part_key
from fusion.script_safety import check_body
from validation.part_checks import derived_check, geometry_of, part_checks
from vehicle.models import ValidationResult, now_iso
from vehicle.palette import Paint, paint_for
from vehicle.parts import FiaRef, PartRecord, PartSpec, script_hash
from vehicle.transforms import matrix_to_fusion_cm, pose_to_matrix


@dataclass
class PartBuild:
    spec: PartSpec
    body: str
    ok: bool                                   # script ran and measured (checks may still fail)
    stage: str                                 # validate | document | prepare | body | place | measure | done
    data: dict = field(default_factory=dict)   # prelude result
    checks: list[ValidationResult] = field(default_factory=list)
    error: str = ""
    script_calls: int = 0
    frame_mode: str = "part_local"

    @property
    def passed(self) -> bool:
        return self.ok and not any(c.blocking_failure for c in self.checks)

    @property
    def depth(self) -> Optional[int]:
        return self.data.get("depth")


def build_config(spec: PartSpec, namespace: str, doc_tag: str, create_doc: bool,
                 paint: Optional[Paint] = None) -> dict:
    """paint: vehicle.palette.paint_for(...) with the project palette; None = the built-in default colour. Colour
    lives only here (the script config), never in the spec or the script body, so it never changes a version."""
    paint = paint or paint_for(spec.id, spec.mirror_of)
    return {"doc_tag": doc_tag, "create_doc": create_doc, "part_id": spec.id, "name": spec.name,
            "namespace": namespace, "params": dict(spec.dims),
            "matrix_cm": matrix_to_fusion_cm(pose_to_matrix(spec.pose)), "paint": paint.cfg(spec.dims),
            "mirror": spec.mirror_mode == "mirror"}


def build_part(client: FusionMCPClient, spec: PartSpec, body: str, namespace: str, doc_tag: str,
               create_doc: bool = True, frame_mode: str = "part_local", paint: Optional[Paint] = None) -> PartBuild:
    """frame_mode: the script's coordinate frame (vehicle.parts.FrameMode); new scripts are part_local."""
    problems = check_body(body)
    if problems:                                         # never reaches Fusion
        data = {"ok": False, "stage": "validate", "error": "unsafe or invalid body: " + "; ".join(problems[:6]),
                "body_lines": [int(m.group(1)) for m in (re.match(r"line (\d+):", q) for q in problems) if m]}
        return PartBuild(spec, body, False, "validate", data=data, error=data["error"],
                         checks=part_checks(spec, data, frame_mode), frame_mode=frame_mode)
    script = compose_part_script(body, build_config(spec, namespace, doc_tag, create_doc, paint))
    data = client.run_script(script).data or {}
    checks = part_checks(spec, data, frame_mode)
    return PartBuild(spec, body, bool(data.get("ok")), "done" if data.get("ok") else data.get("stage", "?"),
                     data=data, checks=checks, error=data.get("error", ""), script_calls=1, frame_mode=frame_mode)


def compact_error(b: PartBuild, context: int = 2) -> dict:
    """What a repair call gets: the error, failing checks and the failing body lines (+/- context)."""
    lines = b.body.splitlines()
    nums = sorted(set(b.data.get("body_lines") or []))
    snippet = []
    for n in nums[-3:]:
        for k in range(max(1, n - context), min(len(lines), n + context) + 1):
            row = f"{k:4d}{'>' if k == n else ' '} {lines[k - 1]}"
            if row not in snippet:
                snippet.append(row)
    failing = [f"{c.check_id}: {c.message}"[:400] for c in b.checks if c.blocking_failure]
    out = {"stage": b.stage, "error": b.error[:600], "failing_checks": failing, "failing_lines": snippet,
           "measured_bbox": (b.data.get("measure") or {}).get("bbox_world")}
    frame = next((c for c in b.checks if c.check_id == "PART-FRAME" and c.blocking_failure), None)
    if frame is not None:                              # the frame diagnostic carries both boxes (part frame, mm)
        out["measured_bbox_local"] = b.data.get("bbox_local")
        out["expected_local_envelope"] = (frame.limit or {}).get("expected_local")
    return out


def to_record(b: PartBuild, namespace: str, run_id: Optional[str], fia: list[FiaRef],
              frame_note: str = "", derived: Optional[dict] = None) -> PartRecord:
    m = b.data.get("measure") or {}
    return PartRecord(id=b.spec.id, name=b.spec.name, role=b.spec.role, frame_mode=b.frame_mode,
                      frame_note=frame_note, derived=derived or {}, geometry=geometry_of(b.data),
                      spec=b.spec, script_body=b.body,
                      script_sha256=script_hash(b.body), params=m.get("params") or {}, pose=b.spec.pose,
                      bbox_world=m.get("bbox_world"), checks=b.checks, fia=fia, run_id=run_id,
                      fusion={"document": b.data.get("document"), "component": part_key(namespace, b.spec.id) + b.spec.name,
                              "param_prefix": param_prefix(namespace, b.spec.id),
                              "fusion_version": b.data.get("fusion_version"), "built_at": now_iso()})


def rebuild_part(client: FusionMCPClient, rec: PartRecord, namespace: str, doc_tag: str,
                 spec: Optional[PartSpec] = None, create_doc: bool = True, paint: Optional[Paint] = None) -> PartBuild:
    """Rebuild a registered part from its stored script (zero Claude calls). `spec` may move it (new pose) or
    change key dimensions; the default is the stored spec."""
    return build_part(client, spec or rec.spec, rec.script_body, namespace, doc_tag, create_doc, rec.frame_mode,
                      paint=paint)


def derive_part(client: FusionMCPClient, source: PartRecord, source_geometry: dict, spec: PartSpec, namespace: str,
                doc_tag: str, create_doc: bool = True, paint: Optional[Paint] = None) -> PartBuild:
    """Build a derived part (vehicle/mirror.py; spec.mirror_of / mirror_mode) from its source's stored script: ONE
    script call, zero Claude calls. All part checks run as usual, plus PART-DERIVED against the source's exact
    measurement (source_geometry: geometry_of() of the source's build, or its record's geometry)."""
    if spec.mirror_of != source.id or spec.mirror_mode not in ("mirror", "yaw180"):
        raise ValueError(f"{spec.id} is not derived from {source.id}")
    if source.frame_mode != "part_local":
        raise ValueError(f"{source.id} is a legacy_world script; only part-local scripts can be mirrored")
    b = build_part(client, spec, source.script_body, namespace, doc_tag, create_doc, paint=paint)
    if b.ok:
        b.checks.append(derived_check(spec.mirror_mode, source.id, source_geometry, b.data))
    return b
