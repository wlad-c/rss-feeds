#!/usr/bin/env python3
"""Build listening-log-standalone.html (fully offline, no external URLs)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "explore.css").read_text(encoding="utf-8")
    js = (ROOT / "explore.js").read_text(encoding="utf-8")
    chart = (ROOT / "vendor/chart.umd.min.js").read_text(encoding="utf-8")

    if "loadAll" not in js or "__LISTENING_DATA__" not in js:
        raise SystemExit("explore.js missing offline data loader")

    agg = json.loads((ROOT / "tables/aggregates.json").read_text(encoding="utf-8"))
    episodes = json.loads((ROOT / "tables/episodes.json").read_text(encoding="utf-8"))
    podcasts = json.loads((ROOT / "tables/podcasts.json").read_text(encoding="utf-8"))
    themes_path = ROOT / "tables/themes.json"
    episode_themes_path = ROOT / "tables/episode-themes.json"
    notes_path = ROOT / "tables/notes.json"
    countries_path = ROOT / "tables/podcast-countries.json"
    themes = json.loads(themes_path.read_text(encoding="utf-8")) if themes_path.exists() else None
    episode_themes = (
        json.loads(episode_themes_path.read_text(encoding="utf-8"))
        if episode_themes_path.exists()
        else None
    )
    notes = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.exists() else {}
    countries = (
        json.loads(countries_path.read_text(encoding="utf-8")) if countries_path.exists() else None
    )

    # Optional local webfonts (Apple redesign uses system SF stack; keep for any leftovers).
    fonts = {
        "./vendor/fonts/fraunces-latin-500-normal.woff2": "vendor/fonts/fraunces-latin-500-normal.woff2",
        "./vendor/fonts/fraunces-latin-700-normal.woff2": "vendor/fonts/fraunces-latin-700-normal.woff2",
        "./vendor/fonts/figtree-latin-400-normal.woff2": "vendor/fonts/figtree-latin-400-normal.woff2",
        "./vendor/fonts/figtree-latin-500-normal.woff2": "vendor/fonts/figtree-latin-500-normal.woff2",
        "./vendor/fonts/figtree-latin-600-normal.woff2": "vendor/fonts/figtree-latin-600-normal.woff2",
        "./vendor/fonts/figtree-latin-700-normal.woff2": "vendor/fonts/figtree-latin-700-normal.woff2",
    }
    for ref, rel in fonts.items():
        path = ROOT / rel
        if not path.exists():
            continue
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        css = css.replace(f'url("{ref}")', f'url("data:font/woff2;base64,{b64}")')

    html = html.replace(
        '<link rel="stylesheet" href="explore.css" />',
        f"<style>\n{css}\n</style>",
    )
    html = html.replace(
        '<script src="vendor/chart.umd.min.js" defer></script>\n  <script src="explore.js" defer></script>',
        "",
    )
    html = html.replace(
        "Built from your Pocket Casts export in this repo.",
        "Standalone offline build from your GitHub Pocket Casts export. No external network requests.",
    )

    payload = json.dumps(
        {
            "aggregates": agg,
            "episodes": episodes,
            "podcasts": podcasts,
            "themes": themes,
            "episodeThemes": episode_themes,
            "notes": notes,
            "countries": countries,
        },
        separators=(",", ":"),
    )
    boot = (
        f"<script>window.__LISTENING_DATA__={payload};</script>\n"
        f"<script>{chart}</script>\n"
        f"<script>{js}</script>\n"
    )
    html = html.replace("</body>", boot + "</body>")

    out = ROOT / "listening-log-standalone.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
