"""toy-people -> Telegram cloner.

This file is deliberately tiny and stable: it makes in-app updates possible.  An update never overwrites the install
folder; it is stored in  <data>/code/current  and *this* loader puts it in front of the installed modules.
If an updated version fails to start, the previous one is restored automatically.
"""
import os
import sys
from pathlib import Path

__path__ = list(__path__)   # noqa: F821  (package search path; we may prepend the update folder)


def overlay_root() -> Path:
    env = os.environ.get("TPCLONE_CODE_DIR")
    if env:
        return Path(env)
    db = os.environ.get("DB_PATH")
    if db:
        return Path(db).parent / "code"
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    return base / "data" / "code"


def _rollback(root: Path) -> None:
    import shutil
    broken = root / "broken"
    shutil.rmtree(broken, ignore_errors=True)
    cur, prev = root / "current", root / "previous"
    if cur.exists():
        cur.rename(broken)
    if prev.exists():
        prev.rename(cur)
    sys.stderr.write("tpclone: the updated version failed to start - restored the previous version\n")


def _activate() -> None:
    if getattr(sys, "frozen", False):
        return
    probe = os.environ.get("TPCLONE_OVERLAY_CURRENT")          # used by the updater to test a staged update
    root = overlay_root()
    cur = Path(probe) if probe else root / "current"
    if not (cur / "tpclone").is_dir():
        return
    if not probe:
        pending, tried = cur / ".pending", cur / ".tried"
        if pending.exists():
            if tried.exists():            # started once with this update and never became healthy
                _rollback(root)
                cur = root / "current"
                if not (cur / "tpclone").is_dir():
                    return
            elif len(sys.argv) == 1 or "run" in sys.argv[1:]:   # only the real app counts as "the first start"
                tried.write_text("1")
    __path__.insert(0, str(cur / "tpclone"))
    libs = cur / "libs"
    if libs.is_dir():
        sys.path.insert(0, str(libs))
    global _CURRENT
    _CURRENT = cur


_CURRENT = None
_activate()


def mark_boot_ok() -> None:
    """Called once the app is up: the update is healthy, no rollback needed."""
    if _CURRENT is not None:
        for name in (".pending", ".tried"):
            (_CURRENT / name).unlink(missing_ok=True)


def code_version() -> str:
    if _CURRENT is not None and (_CURRENT / "VERSION").is_file():
        return (_CURRENT / "VERSION").read_text().strip()
    return "original download"
