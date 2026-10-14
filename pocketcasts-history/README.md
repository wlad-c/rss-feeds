# Pocket Casts listening history

Snapshot of personal Pocket Casts listening history (episodes, podcasts, progress).

## Browse on GitHub

- [Episodes CSV](./tables/episodes.csv)
- [Podcasts CSV](./tables/podcasts.csv)
- [Recent 500 CSV](./tables/recent.csv)
- [Excel workbook](./PocketCasts_Listening_History.xlsx)

## Browse on iPad

Open the CSV links above in Safari — GitHub shows them as tables.

## Google Sheets (iPad)

1. Open Google Sheets → blank spreadsheet  
2. In **A1** paste:

```
=IMPORTDATA("https://raw.githubusercontent.com/wlad-c/rss-feeds/main/pocketcasts-history/tables/podcasts.csv")
```

For recent episodes use `tables/recent.csv`. Full `episodes.csv` is large; prefer GitHub’s CSV view or the Excel file.

`index.html` is included for a filterable web table once GitHub Pages can be enabled on `gh-pages`.
