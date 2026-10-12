"""Local HTTP server for the web UI (Python standard library only; binds to 127.0.0.1).

Routing and JSON only. Fast mode (default page) -> agent.design_service.DesignService; strict mode (Advanced page,
/advanced) -> agent.service.AgentService.

Fast mode:
    GET  /                                      fast UI       GET  /advanced            strict UI
    POST /api/design {"brief", "attachments"?, "visual_review"?}  start      GET /api/design   run list
    GET  /api/design/<id>                       view model    GET  /api/design/<id>/summary   summary.md
    POST /api/design/<id>/answer {"text"}       POST /api/design/<id>/continue   POST /api/design/<id>/rebuild {"part_id"}
    POST /api/design/<id>/rebuild-assembly -> {"run_id"} (new run: all registered parts into a fresh Fusion design)
    POST /api/design/<id>/rebuild-mirror {"part_id"}  (202; re-derive a mirror_of part from its source's latest version)
    POST /api/design/<id>/recolor               (202; apply palette.json to the run's open design, re-shoot)
    POST /api/design/<id>/render {"views"?: ["iso"|"front"|"top"], "preset"?: draft|standard|final,
                                  "camera"?: perspective|orthographic, "focal_mm"?, "background"?: "#RRGGBB",
                                  "environment"?, "brightness_lux"?, "light_angle_deg"?, "ground_reflections"?,
                                  "ground_roughness"?}
                                                (202; local render, MCP screenshot fallback; progress in the view)
    GET  /api/design/<id>/renders/<RDnn>/<iso|front|top>.png
    POST /api/design/<id>/revise {"target": "<PART-ID>"|"assembly", "instruction"}   (202; progress in the view)
    POST /api/design/<id>/revert {"part_id", "version"}                              (202; a NEW version)
    GET  /api/design/<id>/screenshots/<iso|front|top>.png
    GET  /api/design/<id>/revisions/<Rnn>/<before|after>_<iso|front|top>.png
Strict mode:

    GET  /                              UI page              GET  /api/status          reasoner + Fusion + project
    GET  /static/<file>                 UI assets            GET  /api/runs            run list
    POST /api/runs {"request", "attachments"?: [{"filename","data_base64"}]}  start a run (images only)
    GET  /api/runs/<id>/attachments/IMG-nn  stored image              GET  /api/runs/<id>       run view model
    POST /api/runs/<id>/answer {"question_id","text"}        POST /api/runs/<id>/advance  continue / retry
    GET  /api/runs/<id>/report          report.md (text)     GET  /api/runs/<id>/screenshot  PNG
"""
from __future__ import annotations

import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent.design_service import DesignService
from agent.service import AgentService

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 64 * 1024                       # answers and commands
MAX_UPLOAD_BODY = 30 * 1024 * 1024         # a request with up to 4 images of 5 MB (base64)
_RUN = r"/api/runs/(?P<run>[0-9]{8}-[0-9]{6}-[a-z0-9-]{0,40})"
_DRUN = r"/api/design/(?P<run>[0-9]{8}-[0-9]{6}-[a-z0-9-]{0,40})"


def make_handler(service: AgentService, design: DesignService | None = None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AIEngineeringAgent/0.1"

        def log_message(self, fmt, *args):            # keep the console quiet; errors are returned as JSON
            pass

        # ---------------------------------------------------------- helpers
        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _body(self, limit: int = MAX_BODY) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > limit:
                raise ValueError("request body too large")
            raw = self.rfile.read(n) if n else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(data, dict):
                raise ValueError("JSON object expected")
            return data

        def _route(self, method: str):
            path = self.path.split("?", 1)[0]
            try:
                if method == "GET":
                    return self._get(path)
                return self._post(path)
            except KeyError as e:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(e).strip("'\"")})
            except (ValueError, json.JSONDecodeError) as e:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            except Exception as e:                    # never leak a stack trace to the page, but say what failed
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(e).__name__}: {e}"})

        # ---------------------------------------------------------- routes
        def _get(self, path: str):
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path in ("/advanced", "/advanced.html"):
                return self._static("advanced.html")
            if path.startswith("/api/design"):
                return self._get_design(path)
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path == "/api/status":
                return self._json(200, service.system_status())
            if path == "/api/runs":
                return self._json(200, service.list_runs())
            m = re.fullmatch(_RUN, path)
            if m:
                return self._json(200, service.run_view(m["run"]))
            m = re.fullmatch(_RUN + "/report", path)
            if m:
                text = service.report_text(m["run"])
                if text is None:
                    raise KeyError("report not written yet")
                return self._send(200, text.encode("utf-8"), "text/markdown; charset=utf-8")
            m = re.fullmatch(_RUN + r"/attachments/(?P<att>IMG-\d{2})", path)
            if m:
                p, media_type = service.attachment(m["run"], m["att"])
                return self._send(200, p.read_bytes(), media_type)
            m = re.fullmatch(_RUN + "/screenshot", path)
            if m:
                p = service.screenshot_path(m["run"])
                if p is None:
                    raise KeyError("no screenshot for this run")
                return self._send(200, p.read_bytes(), "image/png")
            raise KeyError(f"no route {path}")

        def _design(self) -> DesignService:
            if design is None:
                raise KeyError("fast mode is not enabled on this server")
            return design

        def _get_design(self, path: str):
            if path == "/api/design":
                return self._json(200, self._design().list_runs())
            m = re.fullmatch(_DRUN, path)
            if m:
                return self._json(200, self._design().run_view(m["run"]))
            m = re.fullmatch(_DRUN + r"/screenshots/(?P<view>iso|front|top)\.png", path)
            if m:
                return self._send(200, self._design().screenshot_path(m["run"], m["view"]).read_bytes(), "image/png")
            m = re.fullmatch(_DRUN + r"/revisions/(?P<rev>R\d{2,3})/(?P<name>(?:before|after)_(?:iso|front|top))\.png",
                             path)
            if m:
                return self._send(200, self._design().revision_image(m["run"], m["rev"], m["name"]).read_bytes(),
                                  "image/png")
            m = re.fullmatch(_DRUN + r"/renders/(?P<rd>RD\d{2,3})/(?P<view>(?:iso|front|top)(?:_full)?)\.png", path)
            if m:
                return self._send(200, self._design().render_path(m["run"], m["rd"], m["view"]).read_bytes(),
                                  "image/png")
            m = re.fullmatch(_DRUN + "/summary", path)
            if m:
                return self._send(200, self._design().summary_text(m["run"]).encode("utf-8"),
                                  "text/markdown; charset=utf-8")
            raise KeyError(f"no route {path}")

        def _post_design(self, path: str):
            if path == "/api/design":
                body = self._body(MAX_UPLOAD_BODY)
                atts = body.get("attachments") or []
                if not isinstance(atts, list):
                    raise ValueError("attachments must be a list")
                run_id = self._design().start(str(body.get("brief", "")), atts, bool(body.get("visual_review")))
                return self._json(201, {"run_id": run_id})
            m = re.fullmatch(_DRUN + "/rebuild-assembly", path)
            if m:
                return self._json(201, {"run_id": self._design().rebuild_assembly(m["run"])})
            m = re.fullmatch(_DRUN + "/(?P<action>answer|continue|rebuild|rebuild-mirror|recolor|render|revise|revert)", path)
            if not m:
                raise KeyError(f"no route {path}")
            b = self._body()
            if m["action"] == "answer":
                self._design().answer(m["run"], str(b.get("text", "")))
            elif m["action"] == "continue":
                self._design().resume(m["run"])
            elif m["action"] == "revise":
                self._design().revise(m["run"], str(b.get("target", "")), str(b.get("instruction", "")))
            elif m["action"] == "revert":
                self._design().revert(m["run"], str(b.get("part_id", "")), b.get("version"))
            elif m["action"] == "recolor":
                self._design().recolor(m["run"])
            elif m["action"] == "render":
                views = b.get("views")
                if views is not None and not isinstance(views, list):
                    raise ValueError("views must be a list")
                self._design().render(m["run"], views, {k: v for k, v in b.items() if k != "views"})
            elif m["action"] == "rebuild-mirror":
                self._design().rebuild_mirror(m["run"], str(b.get("part_id", "")))
            else:
                self._design().rebuild(m["run"], str(b.get("part_id", "")))
            return self._json(202, {"ok": True})

        def _post(self, path: str):
            if path.startswith("/api/design"):
                return self._post_design(path)
            if path == "/api/runs":
                body = self._body(MAX_UPLOAD_BODY)
                atts = body.get("attachments") or []
                if not isinstance(atts, list):
                    raise ValueError("attachments must be a list")
                run_id = service.start_run(str(body.get("request", "")), atts)
                return self._json(201, {"run_id": run_id})
            m = re.fullmatch(_RUN + "/answer", path)
            if m:
                b = self._body()
                service.answer(m["run"], str(b.get("question_id", "")), str(b.get("text", "")))
                return self._json(202, {"ok": True})
            m = re.fullmatch(_RUN + "/advance", path)
            if m:
                service.advance(m["run"])
                return self._json(202, {"ok": True})
            raise KeyError(f"no route {path}")

        def _static(self, name: str):
            p = (STATIC / name).resolve()
            if STATIC not in p.parents or not p.is_file():          # no path traversal
                raise KeyError(f"no file {name}")
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            self._send(200, p.read_bytes(), ctype)

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

    return Handler


def make_server(service: AgentService, port: int = 8765, host: str = "127.0.0.1",
                design: DesignService | None = None) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("the UI server only binds to localhost")
    srv = ThreadingHTTPServer((host, port), make_handler(service, design))
    srv.daemon_threads = True
    return srv
