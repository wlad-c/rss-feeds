# Pocket Casts listening history

Personal Pocket Casts listening history + **Listening Log** explorer.

Everything lives in this GitHub repository. No third-party hosts or CDNs.

## Live site

**https://wlad-c.github.io/rss-feeds/**

## Interactive explorer (offline)

Download the single-file app from this repo, then open it on your phone/iPad/laptop:

**[`listening-log-standalone.html`](./listening-log-standalone.html)**

It includes the full history, charts, theme suggestions, topic search, filters, year-over-year comparison, and a listening calendar. It makes **no network requests**.

There is also a multi-file version (`index.html` + `explore.js` + `tables/`) for local HTTP preview:

```bash
cd pocketcasts-history
python3 -m http.server 8765
```

## Chart snapshots (view on GitHub)

![Overview](./charts/overview.png)

![Trends](./charts/trends.png)

![Shows](./charts/shows.png)

![Patterns](./charts/patterns.png)

## Tables

- [Episodes CSV](./tables/episodes.csv)
- [Podcasts CSV](./tables/podcasts.csv)
- [Recent 500 CSV](./tables/recent.csv)
- [Excel workbook](./PocketCasts_Listening_History.xlsx)
- [Aggregates JSON](./tables/aggregates.json)
- [Themes JSON](./tables/themes.json) — suggested topics across listened episodes
- [Notes / transcripts JSON](./tables/notes.json) — RSS show notes + published transcripts where available
- [History coverage](./tables/coverage.json) — account stats + years probed (2010–2018 empty)
- [Played without timestamp](./tables/played_without_listen_timestamp.json) — marked-played episodes with no listen date

Per-episode Listening History from Pocket Casts begins **2019-03-07**. Account stats start **2015-09-11**, but `/history/year` returns **0** rows for 2010–2018 (history was never cleared).

## Themes & searchable notes

Episode **themes** are inferred from titles across the full history (news titles are dense topic labels). Where podcast RSS feeds publish show notes or Podcasting 2.0 `podcast:transcript` files, those texts are stored for search too.

Rebuild theme tags + notes (network required for RSS):

```bash
python3 scripts/build_themes_and_notes.py
```

## Rebuild standalone file

```bash
python3 build-standalone.py
```
