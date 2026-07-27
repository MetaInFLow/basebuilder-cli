#!/usr/bin/env python3
"""Check whether the installed BaseBuilder CLI matches GitHub main."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


REPOSITORY_URL = "https://github.com/MetaInFLow/basebuilder-cli.git"
REMOTE_REF = "refs/heads/main"


def run(command: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def basebuilder_python() -> str | None:
    executable = shutil.which("basebuilder")
    if not executable:
        return None

    try:
        first_line = Path(executable).read_text(errors="ignore").splitlines()[0]
    except (OSError, IndexError):
        return sys.executable

    if not first_line.startswith("#!"):
        return sys.executable

    parts = shlex.split(first_line[2:].strip())
    if not parts:
        return sys.executable
    if Path(parts[0]).name == "env" and len(parts) > 1:
        return shutil.which(parts[1]) or parts[1]
    return parts[0]


def installed_metadata(python: str) -> dict[str, object]:
    code = r'''
import importlib
import json
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

try:
    dist = distribution("basebuilder-cli")
except PackageNotFoundError:
    print(json.dumps({"installed": False}))
    raise SystemExit(0)

direct_url_text = dist.read_text("direct_url.json") or "{}"
try:
    direct_url = json.loads(direct_url_text)
except json.JSONDecodeError:
    direct_url = {}

module = importlib.import_module("basebuilder_cli")
print(json.dumps({
    "installed": True,
    "version": dist.version,
    "module_path": str(Path(module.__file__).resolve()),
    "direct_url": direct_url,
}))
'''
    result = run([python, "-c", code])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "failed to inspect basebuilder-cli")
    return json.loads(result.stdout)


def local_source_info(metadata: dict[str, object]) -> dict[str, object]:
    direct_url = metadata.get("direct_url")
    direct_url = direct_url if isinstance(direct_url, dict) else {}
    vcs_info = direct_url.get("vcs_info")
    vcs_info = vcs_info if isinstance(vcs_info, dict) else {}
    dir_info = direct_url.get("dir_info")
    dir_info = dir_info if isinstance(dir_info, dict) else {}
    source_url = str(direct_url.get("url") or "")
    commit = str(vcs_info.get("commit_id") or "")
    editable = bool(dir_info.get("editable"))
    source_path = ""
    dirty = False

    if source_url.startswith("file:"):
        source_path = unquote(urlparse(source_url).path)
        revision = run(["git", "-C", source_path, "rev-parse", "HEAD"])
        if revision.returncode == 0:
            commit = revision.stdout.strip()
            changes = run(["git", "-C", source_path, "status", "--porcelain"])
            dirty = changes.returncode == 0 and bool(changes.stdout.strip())

    return {
        "commit": commit,
        "editable": editable,
        "dirty": dirty,
        "source_url": source_url,
        "source_path": source_path,
    }


def latest_commit() -> str:
    result = run(["git", "ls-remote", REPOSITORY_URL, REMOTE_REF])
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(result.stderr.strip() or "GitHub main is unavailable")
    return result.stdout.split()[0]


def classify(local_commit: str, remote_commit: str, *, editable: bool) -> str:
    if not local_commit:
        return "unknown"
    if local_commit == remote_commit:
        return "up_to_date"
    if editable:
        return "editable_source_differs"
    return "update_available"


def check() -> dict[str, object]:
    python = basebuilder_python()
    if not python:
        return {"status": "not_installed", "repository": REPOSITORY_URL}

    try:
        metadata = installed_metadata(python)
        if not metadata.get("installed"):
            return {"status": "not_installed", "repository": REPOSITORY_URL}
        source = local_source_info(metadata)
        remote_commit = latest_commit()
        local_commit = str(source["commit"])
        return {
            "status": classify(local_commit, remote_commit, editable=bool(source["editable"])),
            "installed_version": metadata.get("version"),
            "installed_commit": local_commit or None,
            "latest_commit": remote_commit,
            "editable": source["editable"],
            "dirty": source["dirty"],
            "source_url": source["source_url"],
            "source_path": source["source_path"] or None,
            "repository": REPOSITORY_URL,
        }
    except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return {
            "status": "check_failed",
            "error": str(exc),
            "repository": REPOSITORY_URL,
        }


if __name__ == "__main__":
    print(json.dumps(check(), ensure_ascii=False))
