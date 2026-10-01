"""In-app updates: download the repo as a zip, verify, swap in, restart.

Updates live in <data>/code/current (see tpclone/__init__.py), never in the install folder, so the same mechanism works
for a plain install, a VPS and Docker.  Your data (ledger, settings, backups) is never touched.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx

import tpclone
from .config import Settings

MAX_ZIP = 30 * 1024 * 1024
HASHED = (".py", ".html")


class UpdateError(Exception):
    pass


def _download(s: Settings) -> bytes:
    url = f"{s.update_api_base.rstrip('/')}/repos/{s.update_repo}/zipball/{s.update_branch}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "tpclone-updater"}
    if s.update_token:
        headers["Authorization"] = f"Bearer {s.update_token}"
    try:
        with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=60) as r:
            if r.status_code == 404:
                raise UpdateError("Update source not found. If the repository is private, set UPDATE_TOKEN "
                                  "(a GitHub token with read access).")
            if r.status_code in (401, 403):
                raise UpdateError(f"GitHub refused the download (HTTP {r.status_code}); try again later or set UPDATE_TOKEN.")
            r.raise_for_status()
            buf = io.BytesIO()
            for chunk in r.iter_bytes():
                buf.write(chunk)
                if buf.tell() > MAX_ZIP:
                    raise UpdateError("update file is unexpectedly large - refusing")
            return buf.getvalue()
    except httpx.HTTPError as e:
        raise UpdateError(f"cannot reach GitHub: {e}") from e


def _members(z: zipfile.ZipFile) -> tuple[str, list[zipfile.ZipInfo]]:
    names = z.namelist()
    if not names:
        raise UpdateError("empty update file")
    top = names[0].split("/")[0] + "/"
    out = []
    for i in z.infolist():
        if not i.filename.startswith(top):
            raise UpdateError("unexpected update layout")
        rel = i.filename[len(top):]
        if ".." in Path(rel).parts or rel.startswith("/") or os.path.isabs(rel):    # zip-slip guard
            raise UpdateError(f"unsafe path in update: {rel}")
        out.append(i)
    return top, out


def _version_from_top(top: str) -> str:
    m = re.search(r"-([0-9a-f]{7,40})/$", top)
    return m.group(1)[:7] if m else time.strftime("%Y%m%d%H%M")


def _hash_tree(files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode()); h.update(b"\0"); h.update(files[name]); h.update(b"\0")
    return h.hexdigest()


def _remote_files(z: zipfile.ZipFile, top: str, members) -> dict[str, bytes]:
    out = {}
    for i in members:
        rel = i.filename[len(top):]
        if rel.startswith("tpclone/") and rel.endswith(HASHED) and not rel.endswith("/__init__.py") and not i.is_dir():
            out[rel[len("tpclone/"):]] = z.read(i)
    return out


def _local_files() -> dict[str, bytes]:
    pkg = Path(tpclone.__path__[0])
    out = {}
    for p in pkg.rglob("*"):
        if p.is_file() and p.suffix in HASHED and p.name != "__init__.py" and "__pycache__" not in p.parts:
            out[p.relative_to(pkg).as_posix()] = p.read_bytes()
    return out


def check(s: Settings) -> dict:
    """-> {available, remote, local, changed:[files]} ; raises UpdateError."""
    if getattr(sys, "frozen", False):
        raise UpdateError("This packaged app can't update itself: download the new version from the Releases page.")
    data = _download(s)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        top, members = _members(z)
        remote = _remote_files(z, top, members)
    local = _local_files()
    changed = sorted(n for n in set(remote) | set(local) if remote.get(n) != local.get(n))
    return {"available": bool(changed) and _hash_tree(remote) != _hash_tree(local), "remote": _version_from_top(top),
            "local": tpclone.code_version(), "changed": changed, "checked_at": time.time()}


def apply(s: Settings, progress=lambda m: None) -> dict:
    """Download, stage, verify in a throw-away interpreter, then swap. The caller restarts the process."""
    if getattr(sys, "frozen", False):
        raise UpdateError("This packaged app can't update itself: download the new version from the Releases page.")
    progress("downloading the new version")
    data = _download(s)
    root = tpclone.overlay_root()
    staging = root / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            top, members = _members(z)
            for i in members:
                rel = i.filename[len(top):]
                if not rel or i.is_dir():
                    continue
                if rel.startswith("tpclone/") or rel in ("requirements.txt",):
                    dest = staging / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(z.read(i))
            version = _version_from_top(top)
        if not (staging / "tpclone" / "cli.py").is_file():
            raise UpdateError("the downloaded update looks incomplete - nothing changed")
        (staging / "VERSION").write_text(version)

        # new libraries needed?  (only when requirements.txt changed compared with what is running)
        new_req = (staging / "requirements.txt").read_text() if (staging / "requirements.txt").is_file() else ""
        cur = tpclone._CURRENT
        old_req = ""
        for cand in ([cur / "requirements.txt"] if cur else []) + [Path.cwd() / "requirements.txt"]:
            if cand.is_file():
                old_req = cand.read_text()
                break
        if new_req.strip() and new_req != old_req:
            progress("installing new components")
            r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                                "-r", str(staging / "requirements.txt"), "--target", str(staging / "libs")],
                               capture_output=True, text=True, timeout=900)
            if r.returncode != 0:
                raise UpdateError("could not install new components: " + (r.stderr or r.stdout)[-300:])

        progress("testing the new version")
        base_dir = str(Path(tpclone.__file__).resolve().parent.parent)     # where the installed package lives
        env = dict(os.environ, TPCLONE_OVERLAY_CURRENT=str(staging),
                   PYTHONPATH=os.pathsep.join(filter(None, [base_dir, os.environ.get("PYTHONPATH", "")])))
        r = subprocess.run([sys.executable, "-c",
                            "import tpclone.cli, tpclone.web, tpclone.engine, tpclone.updater; print('ok')"],
                           env=env, capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or "ok" not in r.stdout:
            raise UpdateError("the new version failed its self-test, so it was NOT installed: "
                              + (r.stderr or r.stdout)[-300:])

        progress("installing")
        (staging / ".pending").write_text("1")          # until it boots healthy, a failed start rolls back
        current, previous = root / "current", root / "previous"
        shutil.rmtree(previous, ignore_errors=True)
        if current.exists():
            current.rename(previous)
        staging.rename(current)
        return {"version": version, "changed_from": tpclone.code_version()}
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
