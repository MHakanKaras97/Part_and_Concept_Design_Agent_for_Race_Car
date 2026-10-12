"""Start the web UI:  python -m ui [--port 8765] [--project mini_f1] [--strict-project prototype_bench] [--no-browser]

Default page = fast mode (one brief -> assembled concept in Fusion). /advanced = the strict 8-stage workflow.
Claude: the logged-in Claude Code (`claude -p`); env AGENT_MODEL overrides the model.
"""
from __future__ import annotations

import argparse
import sys
import webbrowser

from agent.design_run import DEFAULT_PROJECT
from agent.design_service import DesignService
from agent.service import AgentService
from ui.server import make_server


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ui", description="AI Engineering Agent - web interface")
    ap.add_argument("--project", default=DEFAULT_PROJECT, help="fast-mode project (default: mini_f1)")
    ap.add_argument("--strict-project", default="prototype_bench", help="project of the Advanced (strict) page")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--reasoner", choices=["auto", "claude_code", "file_exchange"], default="auto",
                    help="strict mode only: auto = Claude Code non-interactive if available, else file exchange")
    ap.add_argument("--model", default=None, help="strict mode model (fast mode: env AGENT_MODEL)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    service = AgentService(project=args.strict_project, reasoner=args.reasoner, claude_model=args.model)
    design = DesignService(project=args.project)
    srv = make_server(service, args.port, design=design)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"AI Engineering Agent UI on {url}   (fast mode: project {args.project}; Advanced: {url}advanced)")
    print(f"Strict-mode reasoner: {service.reasoner['mode']} - {service.reasoner['detail']}")
    print("Keep the Fusion window visible: screenshots are taken from its viewport. Ctrl+C to stop.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
