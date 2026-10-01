"""Settings loaded from environment variables / a .env file."""
from __future__ import annotations

import os
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
    link_title: bool = True
    show_more_label: str = "Show More"
    fetch_backend: str = "auto"
    flaresolverr_url: str = ""
    proxy_url: str = ""
    db_path: str = "data/tpclone.db"
    web_host: str = "127.0.0.1"
    web_port: int = 8080
    web_token: str = ""
    auto_resume: bool = True
    dry_run: bool = False
    selectors_file: str = ""
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    # Telegram never accepts less than this between posts to a channel without risking flood-waits.
    MIN_DELAY = 3.0

    @property
    def effective_delay(self) -> float:
        return max(self.post_delay_seconds, self.MIN_DELAY)

    def validate(self, need_telegram: bool = True) -> None:
        if need_telegram and not self.dry_run:
            if not self.telegram_bot_token or not self.telegram_chat_id:
                raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required (see .env.example)")
        if self.web_host not in ("127.0.0.1", "localhost", "::1") and not self.web_token:
            raise SystemExit("WEB_TOKEN is required when WEB_HOST is not localhost")
        if self.media_mode not in ("auto", "url", "upload"):
            raise SystemExit("MEDIA_MODE must be auto|url|upload")
        if not 1 <= self.max_media <= 50:
            raise SystemExit("MAX_MEDIA must be between 1 and 50 (Telegram hard limit)")


def load_settings(env_file: str = ".env") -> Settings:
    _load_dotenv(Path(env_file))
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
    return s
