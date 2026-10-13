# rss-feeds

Personal podcast RSS feeds for Pocket Casts (and any RSS podcast app).

## Poll Position (The Star)

Automatic feed of every video labelled **Poll Position** from [The Star’s YouTube playlist](https://www.youtube.com/playlist?list=PLUl1gfNnrZcc).

Audio is matched from The Star’s Dailymotion uploads, converted to MP3, and published as a static podcast RSS feed on **GitHub Pages** (free `*.github.io` URL — no custom domain needed).

### Stable feed URL (GitHub Pages)

After Pages is enabled (one-time — see below):

| | |
|---|---|
| Landing | https://wlad-c.github.io/rss-feeds/ |
| **RSS (paste into Pocket Casts)** | **https://wlad-c.github.io/rss-feeds/rss.xml** |
| Pocket Casts web follow | https://pocketcasts.com/follow/https://wlad-c.github.io/rss-feeds/rss.xml |

A GitHub Action syncs new episodes about every 6 hours and redeploys the site.

### One-time: enable GitHub Pages

1. Open https://github.com/wlad-c/rss-feeds/settings/pages  
2. Under **Build and deployment → Source**, choose **Deploy from a branch**  
3. Branch: **`gh-pages`** / folder: **/ (root)** → Save  

Wait a minute, then open https://wlad-c.github.io/rss-feeds/rss.xml

### Add to Pocket Casts

1. Pocket Casts → **Discover**
2. Paste `https://wlad-c.github.io/rss-feeds/rss.xml`
3. Tap **Search** on the keyboard → **Subscribe**

### How sync works

1. Read YouTube playlist `PLUl1gfNnrZcc` (titles containing `Poll Position`)
2. Match each title on The Star’s Dailymotion account
3. Extract MP3s and write `rss.xml` + `media/`
4. Deploy the static tree to the `gh-pages` branch

### Manual / local run

```bash
pip install -r requirements.txt
sudo apt-get install -y ffmpeg   # or brew install ffmpeg

export PUBLIC_BASE_URL=https://wlad-c.github.io/rss-feeds
export PYTHONPATH=$PWD/poll-position
python poll-position/sync.py --publish
```

Optional always-on server (not required when using GitHub Pages):

```bash
python poll-position/server.py
```

### Env vars

| Variable | Default | Purpose |
|---|---|---|
| `PUBLIC_BASE_URL` | `https://<user>.github.io/<repo>` in Actions, else localhost | Absolute URL in RSS enclosures |
| `DATA_DIR` | `./data` | Working state + media |
| `SITE_DIR` | `./site` | Static publish output |
| `YOUTUBE_PLAYLIST_ID` | `PLUl1gfNnrZcc` | Source playlist |
| `DAILYMOTION_USER` | `thestar` | Audio source account |
| `TITLE_FILTER` | `Poll Position` | Title label filter |
