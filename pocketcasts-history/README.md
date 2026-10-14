# Pocket Casts listening history

Snapshot of personal Pocket Casts listening history (episodes, podcasts, progress).

## Browse on GitHub

- [Episodes CSV](./data/episodes.csv)
- [Podcasts CSV](./data/podcasts.csv)
- [Recent 500 CSV](./data/recent.csv)
- [Excel workbook](./PocketCasts_Listening_History.xlsx)

## Mobile / web table

Open [`index.html`](./index.html) via the GitHub Pages URL (see root README) after deploy.

## Google Sheets (iPad)

1. Open Google Sheets → blank spreadsheet  
2. In **A1** paste:

```
=IMPORTDATA("https://raw.githubusercontent.com/wlad-c/rss-feeds/main/pocketcasts-history/data/podcasts.csv")
```

For the recent episode list, use `data/recent.csv` the same way. The full `episodes.csv` is large; prefer the web table or the Excel file.
