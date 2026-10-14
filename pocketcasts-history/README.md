# Pocket Casts listening history

Snapshot of personal Pocket Casts listening history (episodes, podcasts, progress).

## Browse on GitHub

- [Episodes CSV](./tables/episodes.csv)
- [Podcasts CSV](./tables/podcasts.csv)
- [Recent 500 CSV](./tables/recent.csv)
- [Excel workbook](./PocketCasts_Listening_History.xlsx)

## Mobile / web table

Open [`index.html`](./index.html) via the GitHub Pages URL (see root README) after deploy.

## Google Sheets (iPad)

1. Open Google Sheets → blank spreadsheet  
2. In **A1** paste:

```
=IMPORTDATA("https://raw.githubusercontent.com/wlad-c/rss-feeds/main/pocketcasts-history/tables/podcasts.csv")
```

For the recent episode list, use `tables/recent.csv` the same way. The full `episodes.csv` is large; prefer the web table or the Excel file.
