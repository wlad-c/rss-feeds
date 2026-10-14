# Pocket Casts listening history

Personal Pocket Casts listening history + **Listening Log** explorer.

Everything lives in this GitHub repository. No third-party hosts or CDNs.

## Interactive explorer (offline)

Download the single-file app from this repo, then open it on your phone/iPad/laptop:

**[`listening-log-standalone.html`](./listening-log-standalone.html)**

It includes the full history, charts, and filters. It makes **no network requests**.

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

## Rebuild standalone file

```bash
python3 build-standalone.py
```
