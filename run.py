"""
VibeFlow Core entry point.

Usage:
    python run.py
    python run.py --port 8000
    python run.py --host 0.0.0.0
"""

from __future__ import annotations

import argparse
import os

import uvicorn

import config


def main() -> None:
    parser = argparse.ArgumentParser(description="VibeFlow Context Sidecar")
    parser.add_argument("--host", default=config.HOST, help="Bind address")
    parser.add_argument("--port", type=int, default=config.PORT, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    parser.add_argument(
        "--project-root",
        default=config.AUTO_PROJECT_ROOT,
        help="Project to index automatically when the server starts",
    )
    parser.add_argument("--no-index", action="store_true", help="Do not auto-index on startup")
    parser.add_argument("--no-watch", action="store_true", help="Do not start the watcher on startup")
    args = parser.parse_args()

    if args.project_root:
        os.environ["VIBEFLOW_PROJECT_ROOT"] = args.project_root
        config.AUTO_PROJECT_ROOT = args.project_root
    os.environ["VIBEFLOW_AUTO_INDEX"] = "0" if args.no_index else "1"
    os.environ["VIBEFLOW_AUTO_WATCH"] = "0" if args.no_watch else "1"
    config.AUTO_INDEX = not args.no_index
    config.AUTO_WATCH = not args.no_watch

    uvicorn.run(
        "api.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
