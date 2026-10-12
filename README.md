# rss-feeds

Personal podcast RSS feeds for Pocket Casts (and any RSS podcast app).

## Poll Position (The Star)

Automatic feed of every video labelled **Poll Position** from [The Star’s YouTube playlist](https://www.youtube.com/playlist?list=PLUl1gfNnrZcc).

Audio is pulled from The Star’s matching Dailymotion uploads (same titles), converted to MP3, and published as a standard podcast RSS feed that Pocket Casts can follow and auto-queue.

### Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# ffmpeg required for audio extract
sudo apt-get install -y ffmpeg   # or brew install ffmpeg

cd poll-position
PUBLIC_BASE_URL=http://127.0.0.1:8787 python server.py
```

Open `http://127.0.0.1:8787/` — the page shows one-tap Pocket Casts links plus the raw RSS URL.

### Add to Pocket Casts

1. Start the server with a **stable public HTTPS URL** (see hosting below).
2. In Pocket Casts → **Discover**, paste:
   `https://YOUR-HOST/rss.xml`
3. Tap **Search** on the keyboard, then **Subscribe**.

Deep links also work:

- App: `pktc://subscribe/YOUR-HOST/rss.xml`
- Web: `https://pocketcasts.com/follow/https://YOUR-HOST/rss.xml`

New Poll Position uploads sync automatically every hour (override with `SYNC_INTERVAL_SECONDS`).

### Docker

```bash
export PUBLIC_BASE_URL=https://your-tunnel-or-host.example
docker compose up --build -d
```

### Public URL via Cloudflare Tunnel (ephemeral)

```bash
# terminal 1
PUBLIC_BASE_URL=http://127.0.0.1:8787 python poll-position/server.py

# terminal 2 — copy the https://….trycloudflare.com URL it prints
cloudflared tunnel --url http://127.0.0.1:8787
```

Then restart the server with `PUBLIC_BASE_URL` set to that HTTPS URL so enclosure links in the feed are correct:

```bash
PUBLIC_BASE_URL=https://….trycloudflare.com python poll-position/server.py
```

For a permanent feed, point a named Cloudflare Tunnel / Fly.io / Railway / any always-on host at port `8787` and keep `PUBLIC_BASE_URL` aligned with that hostname.

### How sync works

1. Read the YouTube playlist `PLUl1gfNnrZcc` (videos titled `… | Poll Position`).
2. Match each title to The Star’s Dailymotion catalogue.
3. Download / extract MP3s into `data/media/`.
4. Regenerate `data/rss.xml` with iTunes tags + audio enclosures.

### Env vars

| Variable | Default | Purpose |
|---|---|---|
| `PUBLIC_BASE_URL` | `http://127.0.0.1:8787` | Absolute URL used in RSS enclosures |
| `PORT` | `8787` | HTTP listen port |
| `DATA_DIR` | `./data` | State, RSS, and media storage |
| `SYNC_INTERVAL_SECONDS` | `3600` | Auto-sync period |
| `YOUTUBE_PLAYLIST_ID` | `PLUl1gfNnrZcc` | Source playlist |
| `DAILYMOTION_USER` | `thestar` | Audio source account |
| `TITLE_FILTER` | `Poll Position` | Title label filter |
