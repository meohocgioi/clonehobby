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


def _headers(s: Settings) -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "tpclone-updater"}
    if s.update_token:
        h["Authorization"] = f"Bearer {s.update_token}"
    return h


def _fetch_zip(s: Settings, branch: str) -> bytes | int:
    """Zip bytes, or the HTTP status code when GitHub says no."""
    url = f"{s.update_api_base.rstrip('/')}/repos/{s.update_repo}/zipball/{branch}"
    with httpx.stream("GET", url, headers=_headers(s), follow_redirects=True, timeout=60) as r:
        if r.status_code != 200:
            return r.status_code
        buf = io.BytesIO()
        for chunk in r.iter_bytes():
            buf.write(chunk)
            if buf.tell() > MAX_ZIP:
                raise UpdateError("update file is unexpectedly large - refusing")
        return buf.getvalue()


def _explain_missing(s: Settings) -> UpdateError:
    """GitHub answered 404/401/403: work out WHY so the message tells the user what to do."""
    try:
        r = httpx.get(f"{s.update_api_base.rstrip('/')}/repos/{s.update_repo}", headers=_headers(s), timeout=30,
                      follow_redirects=True)
    except httpx.HTTPError as e:
        return UpdateError(f"cannot reach GitHub: {e}")
    if r.status_code == 401:
        return UpdateError("GitHub rejected the update access token. Create a new one (GitHub → Settings → Developer "
                           "settings → Personal access tokens, read access to the repository) and paste it in "
                           "Settings → Advanced → Update access token.")
    if r.status_code in (403, 429):
        return UpdateError("GitHub is limiting requests right now; try again in a few minutes.")
    if r.status_code == 404:
        hint = ("The token you entered has no access to it. " if s.update_token else "")
        return UpdateError(f"GitHub can't see the repository “{s.update_repo}”. {hint}It is most likely PRIVATE. Fix it "
                           "either by making the repository public (GitHub → the repository → Settings → scroll to "
                           "“Danger Zone” → Change visibility → Public) or by pasting a GitHub access token in "
                           "Settings → Advanced → Update access token.")
    return UpdateError(f"GitHub answered HTTP {r.status_code} for the repository.")


def _download(s: Settings) -> tuple[bytes, str]:
    """-> (zip bytes, branch actually used). Falls back to the repository's default branch if yours is gone."""
    try:
        got = _fetch_zip(s, s.update_branch)
        if isinstance(got, bytes):
            return got, s.update_branch
        err = _explain_missing(s)
        if "most likely PRIVATE" in str(err) or "token" in str(err) or "limiting" in str(err) or "cannot reach" in str(err):
            raise err
        # repository is reachable, so the BRANCH is the problem: use the default branch
        r = httpx.get(f"{s.update_api_base.rstrip('/')}/repos/{s.update_repo}", headers=_headers(s), timeout=30)
        default = r.json().get("default_branch") if r.status_code == 200 else None
        if default and default != s.update_branch:
            got = _fetch_zip(s, default)
            if isinstance(got, bytes):
                return got, default
        raise UpdateError(f"The update branch “{s.update_branch}” was not found"
                          + (f" (the repository's main branch is “{default}”)" if default else "")
                          + ". Set the right name in Settings → Advanced → Update branch.")
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
    data, branch = _download(s)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        top, members = _members(z)
        remote = _remote_files(z, top, members)
    local = _local_files()
    changed = sorted(n for n in set(remote) | set(local) if remote.get(n) != local.get(n))
    return {"available": bool(changed) and _hash_tree(remote) != _hash_tree(local), "remote": _version_from_top(top),
            "local": tpclone.code_version(), "changed": changed, "checked_at": time.time(), "branch": branch}


def apply(s: Settings, progress=lambda m: None) -> dict:
    """Download, stage, verify in a throw-away interpreter, then swap. The caller restarts the process."""
    if getattr(sys, "frozen", False):
        raise UpdateError("This packaged app can't update itself: download the new version from the Releases page.")
    progress("downloading the new version")
    data, _branch = _download(s)
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
