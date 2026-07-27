#!/usr/bin/env python3
"""Check BaseBuilder CLI against the latest release or GitHub main."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


REPOSITORY_URL = "https://github.com/MetaInFLow/basebuilder-cli.git"
REMOTE_REF = "refs/heads/main"
RELEASE_REFS = "refs/tags/v*"
STABLE_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
STABLE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


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
    requested_revision = str(vcs_info.get("requested_revision") or "")
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
        "requested_revision": requested_revision,
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


def parse_release_tags(output: str) -> dict[str, str]:
    releases: dict[tuple[int, int, int], dict[str, str]] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        commit, ref = parts
        peeled = ref.endswith("^{}")
        ref = ref.removesuffix("^{}")
        tag = ref.removeprefix("refs/tags/")
        match = STABLE_TAG.fullmatch(tag)
        if not match:
            continue
        key = tuple(int(part) for part in match.groups())
        if key not in releases or peeled:
            releases[key] = {
                "version": ".".join(match.groups()),
                "tag": tag,
                "commit": commit,
            }
    if not releases:
        raise RuntimeError("No stable BaseBuilder CLI release is available")
    return releases[max(releases)]


def latest_release() -> dict[str, str]:
    result = run(["git", "ls-remote", "--tags", REPOSITORY_URL, RELEASE_REFS])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "GitHub releases are unavailable")
    return parse_release_tags(result.stdout)


def parse_version(value: str) -> tuple[int, int, int] | None:
    match = STABLE_VERSION.fullmatch(value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def classify_version(installed_version: str, latest_version: str) -> str:
    installed = parse_version(installed_version)
    latest = parse_version(latest_version)
    if installed is None or latest is None:
        return "unknown"
    if installed == latest:
        return "up_to_date"
    if installed > latest:
        return "ahead_of_release"
    return "update_available"


def uses_release_channel(source: dict[str, object]) -> bool:
    if bool(source.get("editable")):
        return False
    requested_revision = str(source.get("requested_revision") or "")
    if STABLE_TAG.fullmatch(requested_revision):
        return True
    if requested_revision:
        return False
    return not bool(source.get("commit"))


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
        local_commit = str(source["commit"])
        release: dict[str, str] = {}
        if uses_release_channel(source):
            release = latest_release()
            status = classify_version(str(metadata.get("version") or ""), release["version"])
            remote_commit = release["commit"]
            comparison = "release"
        else:
            remote_commit = latest_commit()
            status = classify(local_commit, remote_commit, editable=bool(source["editable"]))
            comparison = "main"
        return {
            "status": status,
            "installed_version": metadata.get("version"),
            "installed_commit": local_commit or None,
            "latest_version": release.get("version"),
            "latest_tag": release.get("tag"),
            "latest_commit": remote_commit,
            "comparison": comparison,
            "editable": source["editable"],
            "dirty": source["dirty"],
            "requested_revision": source["requested_revision"] or None,
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
