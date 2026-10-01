# toy-people → Telegram (Rich Message cloner)

> **Not a developer? Read [START-HERE.md](START-HERE.md)** (double-click launcher, or 5 pasted lines on a VPS; everything else is set up in the browser).

Watches <https://www.toy-people.com/en/> 24/7 and republishes every new post to your Telegram channel as a
**Rich Message** (`sendRichMessage`, HTML style), in the same structure as the website.

```
<h3>Title</h3>                 ← preview post
cover photo
[ Show More ]                  ← collapsed <details>; tapping expands the full post in place
   Scheduled Release (italic, omitted when the post has none)
   Hashtags (italic, as on the web)
   Text body
   All photos in one <tg-collage>
   via: source  (italic, hyperlink)
```

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
python -m tpclone check         # verifies bot/channel rights, sitemap and article parsing   <-- run this first
python -m tpclone send-test     # posts one tiny rich message to confirm the channel renders them
python -m tpclone run --start   # dashboard on http://127.0.0.1:8080 , publishing begins immediately
```

The bot must be an **administrator** of the channel with "Post messages".
For 24/7 operation on a VPS use `deploy/tpclone.service` (systemd restarts it and the app resumes by itself).

## Features

| Feature | How it works |
|---|---|
| **Start / Stop** | Dashboard buttons, or `python -m tpclone ctl start|stop|status`. *Stop* lets the in-flight post finish, then halts; the queue and ledger are in SQLite so *Start* continues exactly where it stopped. After a reboot/crash the app resumes if it was running (`AUTO_RESUME`). |
| **No duplicates, even after downtime** | The ledger (`data/tpclone.db`) is written after every successful send. On restart the app diffs the site's sitemap against it, so only posts it has never seen are queued. A post can't be queued twice: states are `known/skipped/pending/sending/posted/failed/uncertain`, and `posted`/`sending` are never re-queued. |
| **Delay / rate limit** | `POST_DELAY_SECONDS` (default 45 s, floor 3 s, persisted across restarts, ±10 % jitter) + optional `MAX_POSTS_PER_HOUR`. Telegram's published limits are ~20 messages/min per chat and 30/s overall, so 45 s is far below them. `429 retry_after` is always honoured and holds the whole queue. |
| **Repost by date** | Dashboard → pick a date → *Check date*. Or `python -m tpclone repost-date 2026-09-25 [--run]`. Already-published posts are never sent again; if the site later adds posts to a date you already published you get: *"You have already published all posts from 2026-09-25. However, the website has added N new post(s) since then. Would you like to publish only the new posts?"* |
| **>50 photos** | A rich message holds ≤ 50 media. The **cover counts as one**. If the gallery doesn't fit, the first photos stay original and the **last slot is one collage image** of the remaining photos (built with Pillow). The renderer asserts it never emits more than `MAX_MEDIA` (≤ 50) images. |
| **Cloudflare** | The site sits behind Cloudflare. `FETCH_BACKEND=auto` tries plain HTTP, then FlareSolverr (`FLARESOLVERR_URL`) or a real Chromium (`pip install playwright && playwright install chromium`). |

## Things you should know (honest limitations)

* **The parser is untested against live article HTML.** From my build environment the sitemap was reachable but
  article pages returned a Cloudflare challenge, so I built the parser from your screenshots + common patterns
  (OpenGraph cover, `article:published_time`, tag links, `via:` line, "Scheduled Release" label) and verified it
  on a synthetic page. **Before going live run `python -m tpclone inspect <post id>`** – it prints what is extracted
  and the final rich HTML. If something is off, fix it without code via a selectors file (`SELECTORS_FILE=selectors.json`):
  ```json
  {"title":"h1.post-title","body":".post-content","tags":".tag-list a","scheduled":".release","credit":".via","date":"time.date","remove":[".ad"]}
  ```
* **Not tested against real Telegram** (no bot token here). The payload follows the Bot API spec for
  `sendRichMessage` / `<details>` / `<tg-collage>` and is covered by mock tests. `send-test` is the quick real check.
* **"Scan the Telegram channel" is impossible with a bot** – the Bot API cannot read channel history. The ledger is the
  source of truth. If you lose it (or want to seed it from posts made before this app), either
  `python -m tpclone import-history result.json` (Telegram Desktop → channel → Export chat history → JSON) or
  `python -m tpclone scan-channel` (optional, uses your own account via Telethon). Posts are recognised by the
  toy-people link on the H3 title (`LINK_TITLE=true`, default) or by title text.
* **First start never floods the channel**: all posts currently on the site are marked *seen, not posted*
  (`INITIAL_POST_LATEST=N` also posts the latest N). If > `MAX_AUTO_QUEUE` unseen posts appear in one poll, they are
  not auto-queued (looks like a site reshuffle); use *Repost by date*.
* **Uncertain deliveries are never re-sent automatically.** If the connection drops after the request left (or the
  process dies mid-send) the post is marked `uncertain`; the dashboard lets you say "it's in the channel" or "send again".
* "Show More" is a collapsible `<details>` block in the same message (works even while the app is off). Hashtags are
  shown exactly as on the web; `HASHTAG_STYLE=hashtag` turns them into clickable `#Tags`.
* Date repost locates a day by binary search over post IDs (IDs grow with time) plus the newest 60 IDs; a back-dated
  post with an old ID far from its day's neighbours won't be found.
* Dates are interpreted in `SITE_TZ` (default `Asia/Taipei`).

## Commands

```
run [--start]            app: worker + dashboard          check            verify setup
ctl start|stop|status    control a running instance        inspect ID|URL   show parsed fields + rich HTML (--html FILE offline, --save)
preview ID               rich HTML of a post, no send      repost-date D    plan + queue (+ --run to publish now)
import-history FILE      seed ledger from an export        scan-channel     seed ledger via Telethon
send-test                one tiny rich message
```

Dashboard security: bound to localhost by default. To expose it set `WEB_HOST=0.0.0.0` **and** `WEB_TOKEN`
(open `/?token=...` once), preferably behind HTTPS/VPN.

## Tests

`pip install pytest && python -m pytest` – 39 tests incl. an end-to-end run over real HTTP against mock site/Telegram.
