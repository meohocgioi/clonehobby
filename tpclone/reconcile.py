"""Rebuild / verify the ledger from what is really in the Telegram channel.

The Bot API cannot read channel history, so there are two ways to look at it:
  * `tpclone import-history result.json`  - a Telegram Desktop export of the channel (always works)
  * `tpclone scan-channel`                - reads the channel with your own account via Telethon (MTProto), optional
Both recognise a post by (1) a toy-people ?p=ID link anywhere in the message (the H3 title is linked by default),
or (2) its title text matching a title already stored in the ledger.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable

from .config import Settings
from .db import DB

POST_ID_RX = re.compile(r"toy-people\.com/(?:[a-z]{2}/)?\?(?:[^\s\"'<>]*&)?p=(\d+)", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", s.lower(), flags=re.U)


def match_ids(blobs: Iterable[str], db: DB) -> set[int]:
    titles = {pid: _norm(t) for pid, t in db.title_index().items() if len(_norm(t)) >= 12}
    found: set[int] = set()
    for blob in blobs:
        found.update(int(m) for m in POST_ID_RX.findall(blob))
        nb = _norm(blob)
        for pid, nt in titles.items():
            if nt in nb:
                found.add(pid)
    return found


def apply_found(db: DB, ids: set[int], site_base: str) -> dict:
    new_rows, updated = 0, 0
    for pid in sorted(ids):
        if db.get(pid) is None:
            db.upsert_seen(pid, f"{site_base.rstrip('/')}/?p={pid}", None, "posted", "import")
            new_rows += 1
        else:
            before = db.get(pid)["status"]
            if before != "posted":
                db.mark_posted_import(pid)
                updated += 1
    db.log("info", f"history import: {len(ids)} post(s) recognised in the channel "
                   f"({updated} ledger entries corrected, {new_rows} added)")
    return {"recognised": len(ids), "corrected": updated, "added": new_rows}


def import_export(db: DB, path: str, site_base: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf8"))
    msgs = data.get("messages", data if isinstance(data, list) else [])
    blobs = [json.dumps(m, ensure_ascii=False) for m in msgs]
    return apply_found(db, match_ids(blobs, db), site_base)


def scan_channel(db: DB, s: Settings, limit: int = 5000) -> dict:  # pragma: no cover - needs a live account
    try:
        from telethon.sync import TelegramClient
    except ImportError as e:
        raise SystemExit("pip install telethon   (and set TG_API_ID / TG_API_HASH from https://my.telegram.org)") from e
    api_id, api_hash = os.environ.get("TG_API_ID"), os.environ.get("TG_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit("set TG_API_ID and TG_API_HASH (https://my.telegram.org -> API development tools)")
    blobs: list[str] = []
    with TelegramClient(str(Path(s.db_path).with_name("telethon")), int(api_id), api_hash) as client:
        for m in client.iter_messages(s.telegram_chat_id, limit=limit):
            try:
                blobs.append(json.dumps(m.to_dict(), default=str, ensure_ascii=False))
            except Exception:
                blobs.append(m.raw_text or "")
    return apply_found(db, match_ids(blobs, db), s.site_base)
