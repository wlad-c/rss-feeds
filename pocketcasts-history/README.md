# Pocket Casts listening history

Snapshot of personal Pocket Casts listening history, plus an interactive **Listening Log** explorer.

## Listening Log (charts & explorer)

Live explorer: https://raw.githack.com/wlad-c/rss-feeds/gh-pages/pocketcasts-history/

Or open [`index.html`](./index.html) via local HTTP (see below).

Includes:
- Monthly trend + 3-month average
- Cumulative listens and per-year totals
- Top shows leaderboard (click to filter)
- Folder & play-status mix
- Weekday / hour-of-day habits
- Average episode length by year
- Full episode explorer with search + filters

## Browse tables on GitHub

- [Episodes CSV](./tables/episodes.csv)
- [Podcasts CSV](./tables/podcasts.csv)
- [Recent 500 CSV](./tables/recent.csv)
- [Excel workbook](./PocketCasts_Listening_History.xlsx)
- [Precomputed aggregates](./tables/aggregates.json)

## Local preview

```bash
cd pocketcasts-history
python3 -m http.server 8765
# open http://127.0.0.1:8765/
```

## Google Sheets (iPad)

In a blank sheet, A1:

```
=IMPORTDATA("https://raw.githubusercontent.com/wlad-c/rss-feeds/main/pocketcasts-history/tables/podcasts.csv")
```
