# Start here (no technical knowledge needed)

This app copies every new post from toy-people.com to your Telegram channel, 24/7.
You only need **two things from Telegram** (the page walks you through it): a *bot token* and your *channel name*.

---

## Option A — on your own computer (Windows / Mac)

1. Click the green **Code** button on GitHub → **Download ZIP** → unzip it anywhere (e.g. your Desktop).
2. **Windows:** double-click **`Start-Windows.bat`**.  **Mac:** double-click **`Start-Mac.command`**
   (first time on Mac: right-click → Open).
   * If it says Python is missing, it opens the download page. Install it (tick **"Add python.exe to PATH"**), then double-click again.
   * The first start installs things for 1–3 minutes. Only once.
3. Your browser opens the control page. Follow **"Step 1 — Connect Telegram"**, press **Save & test connection**.
4. Type a post number (e.g. `114949`) in **Preview a post** to see how it will look. Nothing is sent.
5. Press **▶ Start**. Done. Keep the black window open (minimise it).

*Want it to start by itself whenever you turn on the PC?* Windows: double-click **`Auto-start-with-Windows.bat`** once.
Note: a computer that is turned off or asleep can't post. If you stop it for days, nothing is lost: when it starts again it
checks the website and the list of what it already posted, and sends only what is new.

---

## Option B — on a VPS (leave it and forget it)

You need a Linux VPS (Ubuntu is fine). Log in and paste these lines **one at a time** (this is the only "technical" part, copy & paste):

```
curl -fsSL https://get.docker.com | sh
git clone -b claude/vibrant-tesla-uen2xl https://github.com/meohocgioi/clonehobby
cd clonehobby
docker compose up -d
docker compose logs app | grep -i password
```

The last line shows your **dashboard password** and the address. Open `http://YOUR-SERVER-IP:8080/?token=THE-PASSWORD`
in your browser, then follow Step 1 on the page, then press **▶ Start**.

From now on the server keeps it running 24/7, restarts it if anything crashes, and starts it after a reboot.
(Your settings and the list of posted items are in the `data` folder: don't delete it.)

To update later: `cd clonehobby && git pull && docker compose up -d --build`

---

## Using it

| I want to… | Do this |
|---|---|
| Pause / continue | **■ Stop** / **▶ Start** (it continues exactly where it stopped, never repeats a post) |
| Post an older day again | **Repost older posts by date** → pick the date → **Check date** → confirm. Posts already sent are never sent twice. |
| Slow down / speed up | ⚙ Settings → Toy-People (or HPOI) → **Wait between posts** (45 s is safe; Telegram's limit is much looser) |
| Something shows in red | Look at the **Activity** box. "Needs your attention" lists posts where it isn't sure the post arrived: open your channel and click the matching button. |

## If something looks wrong
Use **Preview a post**: if the title, photos, date or text show as missing (⚠), tell me which post number and what's missing, and I'll adjust it.

## Your data is backed up automatically
Once a day the app saves a copy of its "what was posted" list in the `backups` folder inside your data folder (the last 14
are kept) – you don't have to do anything. The dashboard shows where your data folder is. New installs keep it in your
user folder (not next to the app), so **re-downloading or moving the app no longer loses it**.
If the app ever "forgets" what it posted (e.g. you started it from a new folder of an older version), use the
**Import an old posted-list** card on the dashboard and pick your old `tpclone.db` – posts it knew are added, nothing is deleted. If you ever lose it completely, the app can still
rebuild it from a Telegram "Export chat history" file of your channel (`python -m tpclone import-history result.json`).

## Updating the app (one click)
Scroll to the **Updates** card on the dashboard → **Check for updates** → **Update now**.
The app downloads the new version, tests it, restarts itself (a post in progress finishes first) and the page reloads
on its own. Your settings and posted-list are never touched, and if a new version ever fails to start the old one comes
back automatically. The app also checks twice a day by itself and shows a **"🔔 A new version is available"** bar.

* **Private repository?** GitHub then refuses the download ("Update source not found"). Fix it once: either make the
  repository public (GitHub → repository → Settings → Danger Zone → Change visibility), or create a GitHub access token
  with read access and paste it in ⚙ Settings → Updates → Update source → *Access token*.
* The very first time (to get the Update button) you still need the manual update once: re-download the ZIP / run
  `git pull && docker compose up -d --build`. After that, only the button.
* It works the same on your computer and on the VPS/Docker (updates are stored in the `data` folder).
* Needs the launcher window (or Docker/systemd) to be how you started the app, so it can start again by itself.

## Changing the look of the "Show More" button
⚙ Settings → Toy-People → **"Show More" button** (and the emoji next to it). The default is bold CAPITALS with an emoji on both sides,
e.g. **👇 SHOW MORE 👇**. Press **Send style samples to my channel** to see every style in your own Telegram first, then choose and **Save**.
(Telegram rich text has no font sizes, so "bigger" is done with capitals and emoji, which display large.)

## Space between paragraphs
⚙ Settings → Toy-People → **Space between paragraphs**. The default puts a blank line between paragraphs. If your phone shows it
differently than you like, press **Send style samples to my channel**: it also posts three spacing samples (blank line,
empty paragraph, none) so you can pick the one that looks best, then **Save**.

## Duplicates: how the app protects you
The app remembers **every** channel message it ever sent for a post (a re-post creates a second one) and only treats a post
as "gone" when **all** of its messages are deleted. In the date list you see them under each title (`In your channel: #354, #368`);
click one to open it. Before sending anything, the app also checks whether an earlier copy still exists and holds the post back
if it can't tell. If a copy exists that the app doesn't know about (made before this protection existed), click **already in channel?**
under the post and paste the message number or its t.me link.

## Why date checks are faster now
* The app remembers each channel message it confirmed in the last 30 minutes and doesn't ask Telegram about it again.
* While running with nothing to post, it quietly re-confirms your old posts in the background (about 10 questions a minute at
  most, oldest first). A post you delete in Telegram becomes **Post** again within minutes, even without a date check.
* **Check channel for deleted posts** (top card) always asks about everything, ignoring that memory.
* Website pages: after the website's Cloudflare check has been passed once, the app fetches the following pages straight through
  the browser it already opened instead of trying (and failing) the quick way first.

## Automatic posting vs. "Check date"
A "Check date" looks at the website and lists posts; it never posts by itself. But the automatic watcher posts **every recent post
(last 3 days) that was never posted**, even if a date check saw it first. To keep one recent post out of the channel click
**don't auto-post** under its button in the date list (you can still press **Post** yourself). Posts older than 3 days that you only
browsed are never posted behind your back.

## Posts that go live hours after they were created
The website reserves a post's number when an editor starts it and may publish it many hours later; its own lists are rebuilt only once
a day. So the watcher keeps asking about every recent number that does not exist yet: after 5, 15 and 30 minutes, then once an hour,
until the website's daily list covers it. A late post is therefore posted within about an hour of going live (within minutes if it is
on the homepage list). **Check website now** asks about all of them immediately.

## "Uncertain" posts settle themselves
If the connection drops while a post is being sent, nobody knows whether it arrived. The app waits a couple of minutes, then looks at the
message numbers in your channel right after the last one it knew about: a message of its own that it does not know yet **is** that post
(it gets marked as posted), and no such message up to the end of the channel means the post **never arrived** (it is sent again, once).
If anything is unclear - for example two unknown messages for one uncertain post - the post stays under "Needs your attention" for you to decide.

## Also copying hpoi.net (optional, built in)

The same app can copy the newest items of **hpoi.net → 最新情报 (Latest Info)** to your channel, in English:

* Open the dashboard: Toy-People and HPOI sit side by side on one page, each with its own Start/Stop. All settings are under the ⚙ gear at the top right: a menu on the left (Telegram, Toy-People, HPOI, Backups, Updates), and one **Save changes** bar that appears only when you changed something. The update button is next to the gear.
* At the top, **Today** shows a ring chart of what was posted since midnight (Toy-People, HPOI) and what failed or is uncertain.
  It updates by itself the moment something happens (the app tells the page; the page does not keep asking).
  Next to it, **Needs your attention** has a tab per website; a red dot on a tab means something new is waiting there.
  (each remembers its Start/Stop state across restarts).
* The title and the hashtags (maker, characters, series) are translated to English by Google Translate. Hashtags are
  clickable `#` tags. The expanded post shows the release month, the photos in one collage (no credit footer).
* Names the machine gets wrong can be fixed in `hpoi_glossary.json` in your data folder (it already holds the spellings
  you asked for, e.g. 伊地知星歌 → Ijichi Seika). Add lines like `"中文名": "English Name"`; they apply to the next post.
* If Google Translate is busy, the post simply waits and retries – nothing is ever posted untranslated.
* **Repost by date** scrolls down hpoi's Latest Info list page by page until it is past the day you chose (one page every 5 seconds). The first time you press Start, the items already on the list are marked “seen” (not posted); only later ones are posted.
  Use the date table or the preview box (with a product link) to post older items by hand.
* It is polite to the website: one page read every 10 minutes, at least 5 seconds between requests, never the `/api/` area.
* Settings for it are in **⚙ Settings → HPOI** (on/off, wait time, translator); its channel is under ⚙ Settings → Telegram.
