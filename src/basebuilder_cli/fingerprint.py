from __future__ import annotations

import getpass
import hashlib
import json
import platform
import secrets
import socket
import uuid
from pathlib import Path
from typing import Any

from . import __version__


SIGNAL_SCHEMA = "v1"


def build_fingerprint(state_dir: Path) -> dict[str, Any]:
    nonce = load_or_create_install_nonce(state_dir)
    raw_signals = {
        "hostname": socket.gethostname(),
        "username": getpass.getuser(),
        "mac": str(uuid.getnode()),
        "os": platform.system().lower(),
        "arch": platform.machine().lower(),
        "nonce": nonce,
        "signalSchema": SIGNAL_SCHEMA,
    }
    digest = hashlib.sha256(
        json.dumps(raw_signals, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "fingerprint_hash": "sha256:" + digest,
        "fingerprint_signals": {
            "os": raw_signals["os"],
            "arch": raw_signals["arch"],
            "cliVersion": __version__,
            "signalSchema": SIGNAL_SCHEMA,
        },
    }


def load_or_create_install_nonce(state_dir: Path) -> str:
    path = state_dir / "install.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            nonce = str(data.get("install_nonce") or "").strip()
            if nonce:
                return nonce
        except (OSError, json.JSONDecodeError):
            pass

    nonce = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"install_nonce": nonce}, ensure_ascii=False, indent=2))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return nonce
