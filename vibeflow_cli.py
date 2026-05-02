"""
Terminal control plane for VibeFlow Core.

The CLI covers three jobs:
- install/update VibeFlow from a GitHub URL
- manage the local sidecar server
- call the HTTP API from a terminal or an editor task
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import config

DEFAULT_REPO = "https://github.com/alperensu/VibeFlow.git"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "handler"):
        parser.print_help()
        return 0

    try:
        return int(args.handler(args) or 0)
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}: {' '.join(map(str, exc.cmd))}", file=sys.stderr)
        return exc.returncode
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vibeflow", description="VibeFlow terminal manager")
    parser.add_argument("--host", default=config.HOST, help="API host")
    parser.add_argument("--port", type=int, default=config.PORT, help="API port")
    parser.add_argument("--json", action="store_true", help="Print raw JSON responses")

    sub = parser.add_subparsers(dest="command")

    install = sub.add_parser("install", help="Install or update VibeFlow from a GitHub URL")
    install.add_argument("source", nargs="?", default=DEFAULT_REPO, help="GitHub repository URL")
    install.add_argument("--dir", default=None, help="Install directory")
    install.add_argument("--editable", action="store_true", default=True, help="Install package in editable mode")
    install.set_defaults(handler=cmd_install)

    start = sub.add_parser("start", help="Start the local sidecar server")
    add_server_args(start)
    start.add_argument("--project-root", default=".", help="Project to index/watch")
    start.add_argument("--reload", action="store_true", help="Enable uvicorn reload")
    start.add_argument("--no-index", action="store_true", help="Skip startup indexing")
    start.add_argument("--no-watch", action="store_true", help="Skip watchdog")
    start.set_defaults(handler=cmd_start)

    status = sub.add_parser("status", help="Show server health")
    add_server_args(status)
    add_json_arg(status)
    status.set_defaults(handler=cmd_status)

    settings = sub.add_parser("settings", help="Show optimization settings and profiles")
    add_server_args(settings)
    add_json_arg(settings)
    settings.set_defaults(handler=cmd_settings)

    index = sub.add_parser("index", help="Index a project through the running API")
    add_server_args(index)
    add_json_arg(index)
    index.add_argument("project_root", nargs="?", default=".", help="Project root")
    index.add_argument("--no-watch", action="store_true", help="Do not start watcher")
    index.set_defaults(handler=cmd_index)

    context = sub.add_parser("context", help="Build optimized context through the running API")
    add_server_args(context)
    add_json_arg(context)
    context.add_argument("--project-root", default=".", help="Project root")
    context.add_argument("--current-file", default=None, help="Current file relative to project root")
    context.add_argument("--cursor-line", type=int, default=None, help="1-indexed cursor line")
    context.add_argument("--intent", default="", help="Task intent")
    context.add_argument("--profile", default="maximum_savings", help="Optimization profile")
    context.add_argument("--setting", action="append", default=[], help="Override setting as key=value")
    context.add_argument("--max-files", type=int, default=None, help="Override max files")
    context.set_defaults(handler=cmd_context)

    task = sub.add_parser("task", help="Manage Windows logon task")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    task_install = task_sub.add_parser("install", help="Install Windows logon task")
    task_install.add_argument("--port", type=int, default=config.PORT)
    task_install.add_argument("--project-root", default=".", help="Project to watch at logon")
    task_install.add_argument("--task-name", default="VibeFlow Core")
    task_install.set_defaults(handler=cmd_task_install)
    task_remove = task_sub.add_parser("remove", help="Remove Windows logon task")
    task_remove.add_argument("--task-name", default="VibeFlow Core")
    task_remove.set_defaults(handler=cmd_task_remove)

    doctor = sub.add_parser("doctor", help="Check local runtime requirements")
    add_server_args(doctor)
    add_json_arg(doctor)
    doctor.set_defaults(handler=cmd_doctor)

    return parser


def add_server_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=config.HOST, help="API host")
    parser.add_argument("--port", type=int, default=config.PORT, help="API port")


def add_json_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print raw JSON responses")


def cmd_install(args: argparse.Namespace) -> int:
    source = normalize_repo_url(args.source)
    install_dir = Path(args.dir) if args.dir else default_install_dir(source)
    install_dir = install_dir.expanduser().resolve()

    if install_dir.exists() and (install_dir / ".git").exists():
        run(["git", "pull", "--ff-only"], cwd=install_dir)
    elif install_dir.exists() and any(install_dir.iterdir()):
        raise RuntimeError(f"Install directory is not empty and not a git repo: {install_dir}")
    else:
        install_dir.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", source, str(install_dir)])

    python = find_python()
    venv_python = install_dir / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        run(python + ["-m", "venv", ".venv"], cwd=install_dir)

    run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], cwd=install_dir)
    run([str(venv_python), "-m", "pip", "install", "-e", ".[dev]"], cwd=install_dir)

    print(f"VibeFlow installed: {install_dir}")
    print(f"Start: {venv_python} -m vibeflow_cli start --project-root C:\\path\\to\\project")
    print(f"CLI:   {install_dir / '.venv' / 'Scripts' / 'vibeflow.exe'}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        "run.py",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--project-root",
        args.project_root,
    ]
    if args.reload:
        command.append("--reload")
    if args.no_index:
        command.append("--no-index")
    if args.no_watch:
        command.append("--no-watch")
    return run(command, cwd=repo_root())


def cmd_status(args: argparse.Namespace) -> int:
    return print_response(api_get(args, "/health"), args.json)


def cmd_settings(args: argparse.Namespace) -> int:
    return print_response(api_get(args, "/settings/options"), args.json)


def cmd_index(args: argparse.Namespace) -> int:
    payload = {
        "project_root": str(Path(args.project_root).resolve()),
        "watch": not args.no_watch,
    }
    return print_response(api_post(args, "/index", payload), args.json)


def cmd_context(args: argparse.Namespace) -> int:
    settings = parse_settings(args.setting)
    if args.max_files is not None:
        settings["max_files"] = args.max_files
    payload: dict[str, Any] = {
        "project_root": str(Path(args.project_root).resolve()),
        "current_file": args.current_file,
        "cursor_line": args.cursor_line,
        "intent": args.intent,
        "profile": args.profile,
        "settings": settings or None,
    }
    response = api_post(args, "/context", payload)
    if args.json:
        print(json.dumps(response, indent=2))
    else:
        stats = response.get("stats", {})
        print(f"Token saving: {stats.get('estimated_total_token_saving_percent')}%")
        print(f"Files: {stats.get('files_selected')} / Symbols: {stats.get('symbols_selected')}")
        print("Effects:")
        for effect in stats.get("optimization_effects", []):
            value = effect.get("estimated_saved_tokens", effect.get("estimated_cacheable_tokens", "n/a"))
            print(f"- {effect.get('key')}: enabled={effect.get('enabled')} impact={value}")
        print("\n--- context_string ---")
        print(response.get("context_string", ""))
    return 0


def cmd_task_install(args: argparse.Namespace) -> int:
    script = repo_root() / "scripts" / "install-windows-task.ps1"
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-ProjectRoot",
        str(Path(args.project_root).resolve()),
        "-TaskName",
        args.task_name,
        "-Port",
        str(args.port),
    ]
    return run(command, cwd=repo_root())


def cmd_task_remove(args: argparse.Namespace) -> int:
    script = repo_root() / "scripts" / "remove-windows-task.ps1"
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-TaskName",
        args.task_name,
    ]
    return run(command, cwd=repo_root())


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = {
        "python": sys.version.split()[0],
        "repo_root": str(repo_root()),
        "git": command_exists("git"),
        "server": False,
    }
    try:
        api_get(args, "/health", timeout=1)
        checks["server"] = True
    except RuntimeError:
        checks["server"] = False
    return print_response(checks, args.json)


def api_get(args: argparse.Namespace, path: str, timeout: int = 5) -> Any:
    return request_json("GET", api_url(args, path), timeout=timeout)


def api_post(args: argparse.Namespace, path: str, payload: dict[str, Any]) -> Any:
    return request_json("POST", api_url(args, path), payload=payload)


def api_url(args: argparse.Namespace, path: str) -> str:
    return f"http://{args.host}:{args.port}{path}"


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 20,
) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach VibeFlow API at {url}: {exc}") from exc


def print_response(value: Any, raw_json: bool) -> int:
    if raw_json:
        print(json.dumps(value, indent=2))
        return 0
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                print(f"{key}: {json.dumps(item, indent=2)}")
            else:
                print(f"{key}: {item}")
    else:
        print(value)
    return 0


def parse_settings(values: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise RuntimeError(f"Invalid setting override, expected key=value: {value}")
        key, raw = value.split("=", 1)
        parsed[key] = parse_scalar(raw)
    return parsed


def parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "yes", "1", "on"}:
        return True
    if lowered in {"false", "no", "0", "off"}:
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def normalize_repo_url(value: str) -> str:
    if value.startswith("git@"):
        return value
    if value.startswith("https://github.com/"):
        return value if value.endswith(".git") else value.rstrip("/") + ".git"
    if "/" in value and not value.startswith("http"):
        return f"https://github.com/{value.strip('/')}.git"
    raise RuntimeError(f"Unsupported install source: {value}")


def default_install_dir(source: str) -> Path:
    name = source.rstrip("/").removesuffix(".git").split("/")[-1]
    return Path.home() / ".vibeflow" / name


def find_python() -> list[str]:
    candidates = [["python"], ["py", "-3"], ["python3"]]
    for candidate in candidates:
        try:
            subprocess.run(candidate + ["--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return candidate
        except (OSError, subprocess.CalledProcessError):
            continue
    raise RuntimeError("Python 3.11+ was not found on PATH.")


def command_exists(command: str) -> bool:
    try:
        subprocess.run([command, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def run(command: list[str], cwd: Path | None = None) -> int:
    print(f"$ {' '.join(command)}")
    completed = subprocess.run(command, cwd=str(cwd) if cwd else None, check=True)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
