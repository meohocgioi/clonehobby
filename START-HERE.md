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
| Slow down / speed up | Settings → **Wait between posts** (45 s is safe; Telegram's limit is much looser) |
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
  with read access and paste it in Settings → Advanced → *Update access token*.
* The very first time (to get the Update button) you still need the manual update once: re-download the ZIP / run
  `git pull && docker compose up -d --build`. After that, only the button.
* It works the same on your computer and on the VPS/Docker (updates are stored in the `data` folder).
* Needs the launcher window (or Docker/systemd) to be how you started the app, so it can start again by itself.

## Changing the look of the "Show More" button
Settings → **"Show More" button style** (and the emoji next to it). The default is bold CAPITALS with an emoji on both sides,
e.g. **👇 SHOW MORE 👇**. Press **Send style samples to my channel** to see every style in your own Telegram first, then choose and **Save**.
(Telegram rich text has no font sizes, so "bigger" is done with capitals and emoji, which display large.)

## Space between paragraphs
Settings → Advanced → **Space between paragraphs**. The default puts a blank line between paragraphs. If your phone shows it
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
A "Check date" looks at the website and lists posts; it never posts by itself. If it finds a post that is brand new (found since the
automatic watcher's last look), the watcher still posts it at its next check, so a date check can no longer "steal" a post from
the watcher. Posts you browse in older dates are never posted behind your back.
