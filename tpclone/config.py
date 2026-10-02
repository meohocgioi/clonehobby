"""Settings loaded from environment variables / a .env file."""
from __future__ import annotations

import json
import os
import secrets
import sys
from dataclasses import dataclass, fields
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _b(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_api_base: str = "https://api.telegram.org"
    site_base: str = "https://www.toy-people.com/en/"
    listing_url: str = ""               # page whose "Latest News" list is read every check (default: SITE_BASE)
    listing_max_age_days: int = 3       # never auto-post a listed post older than this
    sitemap_url: str = "https://www.toy-people.com/sitemap/sitemap-en.xml"
    site_tz: str = "Asia/Taipei"
    poll_interval_seconds: int = 300
    site_delay_seconds: float = 1.5
    post_delay_seconds: float = 45.0
    max_posts_per_hour: int = 0
    initial_post_latest: int = 0
    max_auto_queue: int = 60
    max_media: int = 50
    media_mode: str = "auto"
    hashtag_style: str = "plain"
    show_more_label: str = "Show More"
    show_more_style: str = "classic"   # classic | highlight | pill | plain  (see SHOW_MORE_STYLES in render.py)
    show_more_emoji: str = "👇"        # shown on both sides of the Show More text (empty = none)
    fetch_backend: str = "auto"
    flaresolverr_url: str = ""
    proxy_url: str = ""
    db_path: str = ""          # default: <app folder>/data/tpclone.db
    browser_channel: str = ""  # "chrome" / "msedge" to use the browser already installed on the computer
    web_host: str = "127.0.0.1"
    web_port: int = 8080
    web_token: str = ""
    auto_resume: bool = True
    dry_run: bool = False
    selectors_file: str = ""
    update_repo: str = "meohocgioi/clonehobby"
    update_branch: str = "claude/vibrant-tesla-uen2xl"
    update_token: str = ""              # only for a private repository (GitHub token, read access)
    update_api_base: str = "https://api.github.com"
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    # Telegram never accepts less than this between posts to a channel without risking flood-waits.
    MIN_DELAY = 3.0

    @property
    def effective_delay(self) -> float:
        return max(self.post_delay_seconds, self.MIN_DELAY)

    @property
    def data_dir(self) -> Path:
        return Path(self.db_path).parent

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    def validate(self, need_telegram: bool = True) -> None:
        if need_telegram and not self.dry_run and not self.telegram_ready:
            raise SystemExit("Telegram is not configured yet (open the dashboard -> Settings)")
        if self.media_mode not in ("auto", "url", "upload"):
            raise SystemExit("MEDIA_MODE must be auto|url|upload")
        if not 1 <= self.max_media <= 50:
            raise SystemExit("MAX_MEDIA must be between 1 and 50 (Telegram hard limit)")


# Fields editable from the dashboard (saved to <data>/settings.json, which wins over .env)
UI_FIELDS = ("telegram_bot_token", "telegram_chat_id", "post_delay_seconds", "poll_interval_seconds",
             "initial_post_latest", "hashtag_style", "media_mode", "show_more_label", "show_more_style", "show_more_emoji",
             "max_posts_per_hour", "site_tz", "update_repo", "update_branch", "update_token")


def app_dir() -> Path:
    """Folder the app was started from (next to the .exe when packaged)."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()


def settings_path(s: Settings) -> Path:
    return s.data_dir / "settings.json"


def save_ui_settings(s: Settings, changes: dict) -> None:
    path = settings_path(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    cur = json.loads(path.read_text(encoding="utf8")) if path.is_file() else {}
    for k, v in changes.items():
        if k in UI_FIELDS:
            cur[k] = v
    path.write_text(json.dumps(cur, indent=2), encoding="utf8")
    try:
        path.chmod(0o600)          # holds the bot token
    except OSError:
        pass


def _coerce(cur, raw):
    if isinstance(cur, bool):
        return raw if isinstance(raw, bool) else _b(str(raw))
    if isinstance(cur, int):
        return int(float(raw))
    if isinstance(cur, float):
        return float(raw)
    return str(raw).strip()


def load_settings(env_file: str = ".env") -> Settings:
    base = app_dir()
    _load_dotenv(base / env_file if not Path(env_file).is_absolute() else Path(env_file))
    s = Settings()
    for f in fields(s):
        key = f.name.upper()
        if key not in os.environ:
            continue
        raw = os.environ[key]
        cur = getattr(s, f.name)
        if isinstance(cur, bool):
            setattr(s, f.name, _b(raw))
        elif isinstance(cur, int):
            setattr(s, f.name, int(raw))
        elif isinstance(cur, float):
            setattr(s, f.name, float(raw))
        else:
            setattr(s, f.name, raw)
    if not s.db_path:
        import tpclone
        s.db_path = str(tpclone.default_data_dir() / "tpclone.db")
    path = settings_path(s)
    if path.is_file():                                   # saved from the dashboard
        for k, v in json.loads(path.read_text(encoding="utf8")).items():
            if k in UI_FIELDS:
                setattr(s, k, _coerce(getattr(s, k), v))
    # exposed on a network (VPS / Docker) -> always protected by a password
    if s.web_host not in ("127.0.0.1", "localhost", "::1") and not s.web_token:
        tokf = s.data_dir / "dashboard_password.txt"
        s.data_dir.mkdir(parents=True, exist_ok=True)
        if not tokf.is_file():
            tokf.write_text(secrets.token_urlsafe(12), encoding="utf8")
        s.web_token = tokf.read_text(encoding="utf8").strip()
    return s
