"""Real subprocess + mock GitHub: good update, rejected broken update, rollback of an update that crashes on start."""
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
ZIP: dict = {"data": b""}


def make_zip(sha: str, patch=None) -> bytes:
    top = f"o-r-{sha}/"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in sorted((ROOT / "tpclone").glob("*")):
            if p.is_file() and p.suffix in (".py", ".html"):
                content = p.read_bytes()
                if patch and p.name in patch:
                    content = patch[p.name](content)
                z.writestr(f"{top}tpclone/{p.name}", content)
        z.writestr(f"{top}requirements.txt", (ROOT / "requirements.txt").read_text())
    return buf.getvalue()


class GH(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        body = ZIP["data"]
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


@pytest.fixture
def stack(tmp_path):
    gh = ThreadingHTTPServer(("127.0.0.1", 0), GH)
    threading.Thread(target=gh.serve_forever, daemon=True).start()
    port = free_port()
    env = dict(os.environ, DB_PATH=str(tmp_path / "data" / "tpclone.db"), WEB_PORT=str(port), NO_PROXY="127.0.0.1",
               UPDATE_API_BASE=f"http://127.0.0.1:{gh.server_port}", UPDATE_REPO="o/r", UPDATE_BRANCH="main",
               PYTHONPATH="", TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="", TPCLONE_CODE_DIR="")
    env.pop("TPCLONE_CODE_DIR")
    procs = []

    def launch():
        p = subprocess.Popen([sys.executable, "-m", "tpclone", "run"], cwd=ROOT, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        procs.append(p)
        return p

    base = f"http://127.0.0.1:{port}"
    yield launch, base, tmp_path
    for p in procs:
        if p.poll() is None:
            p.terminate()
            try: p.wait(15)
            except Exception: p.kill()
    gh.shutdown()


def api(base, path, body=None):
    if body is None:
        return httpx.get(base + path, timeout=10, trust_env=False).json()
    return httpx.post(base + path, json=body, headers={"X-Requested-With": "tpclone"}, timeout=10, trust_env=False).json()


def wait_up(base, tries=100):
    for _ in range(tries):
        try:
            return api(base, "/api/status")
        except Exception:
            time.sleep(0.2)
    raise AssertionError("app did not come up")


def job(base, jid, tries=300):
    for _ in range(tries):
        j = api(base, f"/api/jobs/{jid}")
        if j["state"] != "running":
            return j
        time.sleep(0.2)
    raise AssertionError("job timeout")


def test_good_update_then_up_to_date(stack):
    launch, base, tmp = stack
    p = launch(); st = wait_up(base)
    assert st["version"] == "original download" and "data/code" not in st["code_dir"]
    ZIP["data"] = make_zip("abc1234def", {"engine.py": lambda b: b + b"\n# update 2\n"})
    j = job(base, api(base, "/api/update/check", {})["job"])
    assert j["result"]["available"] is True and j["result"]["changed"] == ["engine.py"]
    j = job(base, api(base, "/api/update/apply", {})["job"])
    assert j["state"] == "done" and j["result"]["version"] == "abc1234", j
    for _ in range(100):                              # app restarts itself (same pid via exec) with the new code
        time.sleep(0.3)
        try:
            st = api(base, "/api/status")
            if st["version"] == "abc1234":
                break
        except Exception:
            pass
    assert st["version"] == "abc1234" and str(tmp / "data" / "code" / "current") in st["code_dir"]
    assert p.poll() is None and not (tmp / "data" / "code" / "current" / ".pending").exists()   # healthy -> marked ok
    j = job(base, api(base, "/api/update/check", {})["job"])
    assert j["result"]["available"] is False                                                     # nothing newer


def test_broken_update_is_rejected_and_nothing_changes(stack):
    launch, base, tmp = stack
    launch(); wait_up(base)
    ZIP["data"] = make_zip("bad0000", {"web.py": lambda b: b + b"\nthis is not python (\n"})
    j = job(base, api(base, "/api/update/apply", {})["job"])
    assert j["state"] == "error" and "self-test" in j["error"]
    assert not (tmp / "data" / "code" / "current").exists() and not (tmp / "data" / "code" / "staging").exists()
    assert api(base, "/api/status")["version"] == "original download"


def test_update_that_crashes_on_start_rolls_back(stack):
    launch, base, tmp = stack
    p = launch(); wait_up(base)
    crash = lambda b: b.replace(b"def cmd_run(s: Settings, a) -> None:\n", b"def cmd_run(s: Settings, a) -> None:\n    raise SystemExit('boom')\n")
    ZIP["data"] = make_zip("crash99", {"cli.py": crash})
    j = job(base, api(base, "/api/update/apply", {})["job"])
    assert j["state"] == "done"                         # imports fine, so the self-test passes ...
    for _ in range(60):                                 # ... but the restarted app dies on start
        if p.poll() is not None:
            break
        time.sleep(0.3)
    assert p.poll() is not None
    assert (tmp / "data" / "code" / "current" / ".tried").exists()
    p2 = launch()                                       # a supervisor (launcher loop / docker / systemd) starts it again
    st = wait_up(base)                                  # -> the loader notices the failed start and restores the old code
    assert st["version"] == "original download" and "data/code/current" not in st["code_dir"]
    assert (tmp / "data" / "code" / "broken").exists()
    assert p2.poll() is None


class Diag(BaseHTTPRequestHandler):
    """Mock GitHub that can play: private repo / missing branch / token required."""
    mode = "private"
    seen_auth: list = []

    def log_message(self, *a): pass

    def _send(self, code, body=b"{}"):
        self.send_response(code); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        Diag.seen_auth.append(self.headers.get("Authorization"))
        if Diag.mode == "private":
            return self._send(404)
        if Diag.mode == "token_needed" and self.headers.get("Authorization") != "Bearer sekret":
            return self._send(404)
        if self.path.endswith("/zipball/main") and Diag.mode == "branch_gone":
            return self._send(404)
        if self.path.endswith("/repos/o/r"):
            return self._send(200, b'{"default_branch": "dev"}')
        return self._send(200, ZIP["data"])


def test_update_explains_private_repo_and_uses_token_and_default_branch(tmp_path):
    from tpclone import updater
    from tpclone.config import Settings
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Diag)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    s = Settings(update_api_base=f"http://127.0.0.1:{srv.server_port}", update_repo="o/r", update_branch="main")
    ZIP["data"] = make_zip("aaaaaaa")
    try:
        Diag.mode = "private"
        with pytest.raises(updater.UpdateError) as e:
            updater.check(s)
        assert "PRIVATE" in str(e.value) and "Update access token" in str(e.value)
        Diag.mode = "token_needed"
        with pytest.raises(updater.UpdateError):
            updater.check(s)
        s.update_token = "sekret"
        assert updater.check(s)["remote"] == "aaaaaaa"                    # the token is sent as a Bearer header
        Diag.mode = "branch_gone"; s.update_token = ""
        r = updater.check(s)                                              # repo reachable, branch gone -> default branch
        assert r["branch"] == "dev"
    finally:
        srv.shutdown()
