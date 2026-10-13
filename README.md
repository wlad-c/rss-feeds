# rss-feeds

Personal podcast RSS feeds for Pocket Casts (and any RSS podcast app).

**Agent rule:** coding agents must merge and deploy their own PRs — never leave work waiting on human review. See [AGENTS.md](./AGENTS.md).

## Feeds

| Podcast | Pocket Casts RSS | Notes |
|---|---|---|
| **Mano a Mano** (Spotify Studios) | https://cdn.jsdelivr.net/gh/wlad-c/rss-feeds@feeds/mano-a-mano/rss.xml | Megaphone mirror on lightweight `feeds` branch; enclosure sizes filled for Pocket Casts |
| **Poll Position** (The Star) | https://cdn.jsdelivr.net/gh/wlad-c/rss-feeds@gh-pages/rss.xml | YouTube → Dailymotion MP3s hosted on `gh-pages` |

---

## Mano a Mano (Spotify)

Spotify show: https://open.spotify.com/show/0GnKiYeK11476CfoQEYlEd

Spotify Studios publishes this show on **Megaphone**. The upstream feed sets every `<enclosure length="0">`, which makes Pocket Casts show **0 bytes** and block downloads. Our mirror probes each audio URL for `Content-Length` and rewrites those attributes. It is published on a tiny `feeds` branch (XML only) so jsDelivr is not blocked by the ~122MB Poll Position media on `gh-pages`.

### Stable feed URL

| | |
|---|---|
| Landing | https://cdn.jsdelivr.net/gh/wlad-c/rss-feeds@feeds/mano-a-mano/ |
| **RSS (paste into Pocket Casts)** | **https://cdn.jsdelivr.net/gh/wlad-c/rss-feeds@feeds/mano-a-mano/rss.xml** |
| Official Megaphone | https://feeds.megaphone.fm/GLT5279624272 |
| Pocket Casts web follow | https://pocketcasts.com/follow/https://cdn.jsdelivr.net/gh/wlad-c/rss-feeds@feeds/mano-a-mano/rss.xml |

### Add to Pocket Casts

1. Pocket Casts → **Discover**
2. Paste `https://cdn.jsdelivr.net/gh/wlad-c/rss-feeds@feeds/mano-a-mano/rss.xml`
3. Tap **Search** on the keyboard → **Subscribe**

### Manual / local run

```bash
export PUBLIC_BASE_URL=https://cdn.jsdelivr.net/gh/wlad-c/rss-feeds@feeds/mano-a-mano
export PYTHONPATH=$PWD/mano-a-mano
python mano-a-mano/sync.py --publish
```

A GitHub Action refreshes the mirror about every 6 hours and force-updates the `feeds` branch.

---

## Poll Position (The Star)

Automatic feed of every video labelled **Poll Position** from [The Star’s YouTube playlist](https://www.youtube.com/playlist?list=PLUl1gfNnrZcc).

Audio is matched from The Star’s Dailymotion uploads, converted to MP3, and published to the `gh-pages` branch. The public podcast URL is the **jsDelivr** CDN mirror of that branch (stable HTTPS, no custom domain, no GitHub Pages site toggle required).

### Stable feed URL

| | |
|---|---|
| Landing | https://cdn.jsdelivr.net/gh/wlad-c/rss-feeds@gh-pages/ |
| **RSS (paste into Pocket Casts)** | **https://cdn.jsdelivr.net/gh/wlad-c/rss-feeds@gh-pages/rss.xml** |
| Pocket Casts web follow | https://pocketcasts.com/follow/https://cdn.jsdelivr.net/gh/wlad-c/rss-feeds@gh-pages/rss.xml |

A GitHub Action syncs new episodes about every 6 hours and force-updates the `gh-pages` branch (preserving sibling feeds such as `mano-a-mano/`).

### Add to Pocket Casts

1. Pocket Casts → **Discover**
2. Paste `https://cdn.jsdelivr.net/gh/wlad-c/rss-feeds@gh-pages/rss.xml`
3. Tap **Search** on the keyboard → **Subscribe**

### How sync works

1. Read YouTube playlist `PLUl1gfNnrZcc` (titles containing `Poll Position`)
2. Match each title on The Star’s Dailymotion account
3. Extract MP3s and write `rss.xml` + `media/`
4. Deploy the static tree to the `gh-pages` branch (CDN picks it up)

### Manual / local run

```bash
pip install -r requirements.txt
sudo apt-get install -y ffmpeg   # or brew install ffmpeg

export PUBLIC_BASE_URL=https://cdn.jsdelivr.net/gh/wlad-c/rss-feeds@gh-pages
export PYTHONPATH=$PWD/poll-position
python poll-position/sync.py --publish
```

### Env vars

| Variable | Default | Purpose |
|---|---|---|
| `PUBLIC_BASE_URL` | jsDelivr `@gh-pages` URL in Actions | Absolute URL in RSS enclosures |
| `DATA_DIR` | `./data` | Working state + media |
| `SITE_DIR` | `./site` | Static publish output |
| `YOUTUBE_PLAYLIST_ID` | `PLUl1gfNnrZcc` | Source playlist |
| `DAILYMOTION_USER` | `thestar` | Audio source account |
| `TITLE_FILTER` | `Poll Position` | Title label filter |
