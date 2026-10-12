"""Image attachments of an engineering request (MVP: images only).

An attachment is source EVIDENCE supplied by the user. It is stored with the run (traceable, hashed) and shown
to the reasoner; it never becomes geometry or a user answer by itself. Anything the AI reads from it is recorded
as image-derived evidence (Requirement source IMAGE), distinct from the user's own words.

Stored as  runs/<run_id>/attachments/IMG-01.png  and listed in run.json["attachments"].
"""
from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import Optional

from vehicle.models import now_iso

MAX_IMAGE_BYTES = 5 * 1024 * 1024        # also the per-image limit Claude accepts
MAX_IMAGES = 4
ATTACHMENT_ID_RE = re.compile(r"^IMG-\d{2}$")
_SIGNATURES = [(b"\x89PNG\r\n\x1a\n", "image/png", "png"), (b"\xff\xd8\xff", "image/jpeg", "jpg"),
               (b"GIF87a", "image/gif", "gif"), (b"GIF89a", "image/gif", "gif")]


def sniff_image(data: bytes) -> Optional[tuple[str, str]]:
    """(media_type, extension) from the file's magic bytes, or None if not a supported image."""
    for sig, mt, ext in _SIGNATURES:
        if data.startswith(sig):
            return mt, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def decode_upload(item: dict) -> tuple[bytes, str]:
    """UI/CLI upload {"filename", "data_base64"} -> (bytes, original filename). Validates size and type."""
    name = Path(str(item.get("filename") or "image")).name[:120]
    try:
        data = base64.b64decode(str(item.get("data_base64") or ""), validate=True)
    except (ValueError, TypeError) as e:
        raise ValueError(f"attachment '{name}' is not valid base64") from e
    check_image(data, name)
    return data, name


def check_image(data: bytes, name: str) -> tuple[str, str]:
    if not data:
        raise ValueError(f"attachment '{name}' is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"attachment '{name}' is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    kind = sniff_image(data)
    if kind is None:
        raise ValueError(f"attachment '{name}' is not a PNG, JPEG, GIF or WebP image")
    return kind


def save_attachments(run_dir: Path, files: list[tuple[bytes, str]], entered_via: str) -> list[dict]:
    """Write validated images into the run folder; return their run.json records."""
    if len(files) > MAX_IMAGES:
        raise ValueError(f"at most {MAX_IMAGES} images per request")
    out = []
    for i, (data, name) in enumerate(files, 1):
        media_type, ext = check_image(data, name)
        att_id = f"IMG-{i:02d}"
        rel = f"attachments/{att_id}.{ext}"
        path = run_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        out.append({"id": att_id, "file": rel, "original_name": name, "media_type": media_type, "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(), "received": now_iso(), "entered_via": entered_via,
                    "role": "user-supplied source evidence"})
    return out


def load_attachment(run_dir: Path, record: dict) -> bytes:
    """Read an attachment and verify it still matches its recorded hash."""
    data = (run_dir / record["file"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise ValueError(f"attachment {record['id']} does not match its recorded SHA-256")
    return data

