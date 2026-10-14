#!/usr/bin/env python3
"""Build theme tags + searchable notes/transcripts for the Listening Log.

Full audio STT across ~9k hours / 22k episodes is not practical in-repo.
This script:

1. Tags every listened episode from its title (dense topic signal for news shows).
2. Resolves RSS feeds for top podcasts via Apple Podcasts search.
3. Matches listened episodes to feed items by normalized title.
4. Pulls show notes and, when present, podcast:transcript / transcript links.

Outputs (under pocketcasts-history/tables/):
  themes.json          — theme catalog + counts + samples
  episode-themes.json  — parallel array of theme-id lists (same order as episodes.json)
  notes.json           — sparse map of episode index → {src, text, url?}
  notes-meta.json      — fetch stats
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "tables"
UA = "rss-feeds-listening-log/1.0 (+https://github.com/wlad-c/rss-feeds)"
MAX_NOTE_CHARS = 500
MAX_TRANSCRIPT_CHARS = 4000
TOP_PODCASTS_FOR_RSS = 30
MAX_TRANSCRIPTS_PER_SHOW = 12
REQUEST_TIMEOUT = 12

# Curated themes for this listening mix (EN/PT/FR news + geopolitics).
# Each pattern is matched case-insensitively against episode titles.
THEMES: list[dict] = [
    {
        "id": "us-politics",
        "name": "US politics & elections",
        "blurb": "White House, Congress, midterms, parties, and US domestic politics.",
        "patterns": [
            r"\btrump\b", r"\bbiden\b", r"\bkamala\b", r"\bharris\b", r"\bmaga\b",
            r"\bcongress\b", r"\bsenate\b", r"\bwhite house\b", r"\bmidterm",
            r"\bdemocrat", r"\brepublican", r"\bgop\b", r"\belection day\b",
            r"\bsupreme court\b", r"\bscotus\b", r"\bimpeach", r"\bfbi\b",
            r"\bice\b", r"\bmamdani\b", r"\bobama\b",
        ],
    },
    {
        "id": "brazil-politics",
        "name": "Brazil politics & elections",
        "blurb": "Lula, Bolsonaro, TSE, Congresso, eleições e política doméstica.",
        "patterns": [
            r"\blula\b", r"\bbolsonar", r"\bflavio bolsonaro\b", r"\bplanalto\b",
            r"\btse\b", r"\tstf\b", r"\bcâmara\b", r"\bcâmara\b", r"\bsenado\b",
            r"\beleiç", r"\beleic", r"\bpt\b", r"\bpmdb\b", r"\bpsdb\b",
            r"\bmoraes\b", r"\bxandão\b", r"\bdatafolha\b", r"\bibrupe\b",
            r"\bprimeiro turno\b", r"\bsegundo turno\b", r"\b2º turno\b",
            r"\bantipetismo\b", r"\bantibolsonar", r"\bbrasil\b",
        ],
    },
    {
        "id": "australia-politics",
        "name": "Australian politics",
        "blurb": "Albanese, Coalition, Labor, Parliament House, and domestic policy.",
        "patterns": [
            r"\balbanese\b", r"\balbo\b", r"\bcoalition\b", r"\blabor\b", r"\blabour\b",
            r"\bliberals?\b", r"\bnationals?\b", r"\bdutton\b", r"\bmorrison\b",
            r"\bparliament house\b", r"\bcanberra\b", r"\bquestion time\b",
            r"\bgreens\b", r"\bone nation\b", r"\brobodebt\b", r"\bvoice\b",
            r"\baustralia\b", r"\baustralian\b",
        ],
    },
    {
        "id": "ukraine-russia",
        "name": "Ukraine & Russia",
        "blurb": "War, diplomacy, sanctions, and Moscow–Kyiv dynamics.",
        "patterns": [
            r"\bukraine\b", r"\bukrainian\b", r"\brussia\b", r"\brussian\b",
            r"\bputin\b", r"\bzelensky", r"\bkyiv\b", r"\bkiev\b", r"\bmoscow\b",
            r"\bkrim\b", r"\bcrimea\b", r"\bdonbas\b", r"\bnato\b",
            r"\búcr[aá]nia\b", r"\br[uú]ssia\b",
        ],
    },
    {
        "id": "middle-east",
        "name": "Middle East",
        "blurb": "Israel, Gaza, Iran, Gulf states, and regional diplomacy.",
        "patterns": [
            r"\bisrael\b", r"\bisraeli\b", r"\bgaza\b", r"\bhamas\b", r"\bhezbollah\b",
            r"\biran\b", r"\biranian\b", r"\btehran\b", r"\bjordan\b", r"\blebanon\b",
            r"\bsyria\b", r"\bsaudi\b", r"\byemen\b", r"\bhouthi", r"\bqatar\b",
            r"\bnetanyahu\b", r"\bwest bank\b", r"\bpaloestin", r"\bpalestin",
            r"\bir[aã]n\b", r"\bisrael\b",
        ],
    },
    {
        "id": "china-indo-pacific",
        "name": "China & Indo-Pacific",
        "blurb": "China, Taiwan, ASEAN, AUKUS, and regional security.",
        "patterns": [
            r"\bchina\b", r"\bchinese\b", r"\bbeijing\b", r"\bxi jinping\b",
            r"\btaiwan\b", r"\bsouth china sea\b", r"\baukus\b", r"\bquad\b",
            r"\basean\b", r"\bsingapore\b", r"\bmalaysia\b", r"\bindonesia\b",
            r"\bphilippines\b", r"\bvietnam\b", r"\bjapan\b", r"\bkorea\b",
            r"\bnorth korea\b", r"\bkim jong\b", r"\bindo-?pacific\b",
            r"\bchin[ae]\b", r"\bsinica\b",
        ],
    },
    {
        "id": "defence-security",
        "name": "Defence & national security",
        "blurb": "Military, intelligence, cyber, and strategic policy.",
        "patterns": [
            r"\bdefence\b", r"\bdefense\b", r"\bmilitary\b", r"\barmy\b", r"\bnavy\b",
            r"\bair force\b", r"\bnuclear\b", r"\bmissile\b", r"\bintel(?:ligence)?\b",
            r"\bcia\b", r"\bnsa\b", r"\bcyber\b", r"\bhack(?:ing|ed|er)?\b",
            r"\bnational security\b", r"\baspi\b", r"\blow[yi]\b",
            r"\bsoberania\b", r"\bdefesa\b",
        ],
    },
    {
        "id": "economy-markets",
        "name": "Economy & markets",
        "blurb": "Inflation, rates, trade, budgets, markets, and business.",
        "patterns": [
            r"\beconomy\b", r"\beconomic\b", r"\binflation\b", r"\binterest rate",
            r"\bfed\b", r"\brecession\b", r"\bmarket", r"\bstock", r"\btrade war\b",
            r"\btariff", r"\bbudget\b", r"\bgdp\b", r"\bunemployment\b",
            r"\beconomia\b", r"\binfla[cç]", r"\bjuro", r"\bmercado\b",
            r"\bpix\b", r"\bmei\b", r"\bip[eo]\b", r"\bsubsidy\b",
        ],
    },
    {
        "id": "climate-energy",
        "name": "Climate & energy",
        "blurb": "Climate policy, renewables, fossils, and the energy transition.",
        "patterns": [
            r"\bclimate\b", r"\bemissions?\b", r"\bnet.?zero\b", r"\brenewable",
            r"\bsolar\b", r"\bwind\b", r"\bcoal\b", r"\boil\b", r"\bgas\b",
            r"\bev\b", r"\belectric vehicle", r"\bnuclear energy\b", r"\bcop\d*\b",
            r"\bclima\b", r"\bamaz[oô]nia\b", r"\benergia\b", r"\bpetr[oó]leo\b",
        ],
    },
    {
        "id": "ai-tech",
        "name": "AI & technology",
        "blurb": "Artificial intelligence, platforms, and digital policy.",
        "patterns": [
            r"(?<![a-z])ai(?![a-z])", r"\bartificial intelligence\b", r"\bchatgpt\b",
            r"\bopenai\b", r"\btechnology\b", r"\bsocial media\b", r"\balgorithm",
            r"\bgoogle\b", r"\btiktok\b", r"\bopenai\b",
            r"\bintellig[eê]ncia artificial\b", r"(?<![a-z])ia(?![a-z])",
            r"\bredes sociais\b",
        ],
    },
    {
        "id": "migration-borders",
        "name": "Migration & borders",
        "blurb": "Immigration, asylum, borders, and demographic politics.",
        "patterns": [
            r"\bmigration\b", r"\bimmigration\b", r"\basylum\b", r"\brefugee",
            r"\bborder\b", r"\bvisa\b", r"\bmigrant", r"\bdeport",
            r"\bimigra", r"\bmigra[cç]", r"\brefugiad",
        ],
    },
    {
        "id": "health-science",
        "name": "Health & science",
        "blurb": "Public health, medicine, pandemics, and research.",
        "patterns": [
            r"\bcovid\b", r"\bpandemic\b", r"\bvaccine\b", r"\bhealth\b",
            r"\bhospital\b", r"\bcancer\b", r"\bdementia\b", r"\bscience\b",
            r"\bsa[uú]de\b", r"\bvacin", r"\bpandemia\b",
        ],
    },
    {
        "id": "media-democracy",
        "name": "Media, rights & democracy",
        "blurb": "Press freedom, disinformation, courts, and democratic norms.",
        "patterns": [
            r"\bdemocrac", r"\bfree speech\b", r"\bdisinfo", r"\bmisinfo",
            r"\bfake news\b", r"\bcensur", r"\bpress freedom\b", r"\bjournalis",
            r"\bsupreme court\b", r"\bconstitui", r"\bdireitos?\b", r"\bvoto\b",
            r"\babsten", r"\beleitoral\b", r"\bextrem[ae]",
        ],
    },
    {
        "id": "diplomacy-global",
        "name": "Diplomacy & global affairs",
        "blurb": "Summits, alliances, foreign policy, and multilateral forums.",
        "patterns": [
            r"\bdiplomacy\b", r"\bdiplomatic\b", r"\bforeign policy\b", r"\bunited nations\b",
            r"\bg20\b", r"\bg7\b", r"\balliance\b", r"\btreaty\b",
            r"\bsanction", r"\bambassador\b", r"\bgeopolitic", r"\bforo de teresina\b",
            r"\bdiplomacia\b", r"\bgeopol[ií]tica\b",
        ],
    },
    {
        "id": "crime-justice",
        "name": "Crime & justice",
        "blurb": "Courts, policing, corruption, and criminal law.",
        "patterns": [
            r"\bcrime\b", r"\bpolice\b", r"\bprosecut", r"\btrial\b", r"\bverdict\b",
            r"\bcorrup", r"\bmurder\b", r"\bassault\b", r"\bjail\b", r"\bprison\b",
            r"\bviol[eê]ncia\b", r"\binseguran", r"\bpol[ií]cia\b", r"\bcrime\b",
        ],
    },
    {
        "id": "weather-disasters",
        "name": "Weather & disasters",
        "blurb": "Hurricanes, floods, fires, and extreme weather.",
        "patterns": [
            r"\bhurricane\b", r"\bflood", r"\bwildfire\b", r"\bearthquake\b",
            r"\bstorm\b", r"\btyphoon\b", r"\bcyclone\b", r"\btornado\b",
            r"\benchente", r"\binc[eê]ndio", r"\bdesastre",
        ],
    },
]


def normalize_title(s: str) -> str:
    s = html.unescape(s or "")
    s = s.lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def strip_html(raw: str) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def http_get(url: str, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": accept},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return resp.read()


def http_get_text(url: str, accept: str = "*/*") -> str:
    data = http_get(url, accept=accept)
    for enc in ("utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def compile_themes() -> list[tuple[dict, list[re.Pattern]]]:
    out = []
    for theme in THEMES:
        pats = [re.compile(p, re.I) for p in theme["patterns"]]
        out.append((theme, pats))
    return out


def tag_episodes(episodes: list[dict]) -> tuple[list[list[str]], dict]:
    compiled = compile_themes()
    counts: Counter = Counter()
    samples: dict[str, list] = defaultdict(list)
    by_year: dict[str, Counter] = defaultdict(Counter)
    tagged: list[list[str]] = []

    for i, ep in enumerate(episodes):
        title = ep.get("e") or ""
        hits = []
        for theme, pats in compiled:
            if any(p.search(title) for p in pats):
                hits.append(theme["id"])
                counts[theme["id"]] += 1
                by_year[theme["id"]][str(ep.get("y") or "")] += 1
                if len(samples[theme["id"]]) < 8:
                    samples[theme["id"]].append(
                        {
                            "i": i,
                            "e": title,
                            "p": ep.get("p"),
                            "d": ep.get("d"),
                        }
                    )
        tagged.append(hits)

    catalog = []
    for theme, _ in compiled:
        tid = theme["id"]
        catalog.append(
            {
                "id": tid,
                "name": theme["name"],
                "blurb": theme["blurb"],
                "count": int(counts.get(tid, 0)),
                "byYear": dict(sorted(by_year[tid].items())),
                "samples": samples[tid],
            }
        )
    catalog.sort(key=lambda t: t["count"], reverse=True)

    coverage = sum(1 for t in tagged if t)
    meta = {
        "totalEpisodes": len(episodes),
        "episodesWithTheme": coverage,
        "themeCount": len(catalog),
        "method": "title-keyword",
        "note": (
            "Themes are inferred from episode titles across the full listening "
            "history. Full audio transcription of ~9k hours is not stored; "
            "search also uses RSS show notes / published transcripts when available."
        ),
    }
    return tagged, {"meta": meta, "themes": catalog}


def itunes_feed_url(podcast_name: str) -> str | None:
    q = urllib.parse.urlencode({"term": podcast_name, "media": "podcast", "limit": 5})
    url = f"https://itunes.apple.com/search?{q}"
    try:
        payload = json.loads(http_get_text(url, accept="application/json"))
    except Exception as exc:  # noqa: BLE001
        print(f"  itunes miss for {podcast_name!r}: {exc}")
        return None
    results = payload.get("results") or []
    name_l = podcast_name.lower()
    for r in results:
        if (r.get("collectionName") or "").lower() == name_l and r.get("feedUrl"):
            return r["feedUrl"]
    for r in results:
        cn = (r.get("collectionName") or "").lower()
        if name_l in cn or cn in name_l:
            if r.get("feedUrl"):
                return r["feedUrl"]
    if results and results[0].get("feedUrl"):
        return results[0]["feedUrl"]
    return None


def localname(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def parse_rss_items(xml_text: str) -> list[dict]:
    # Tolerate imperfect feeds
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        xml_text = re.sub(r"&(?!amp;|lt;|gt;|apos;|quot;)", "&amp;", xml_text)
        root = ET.fromstring(xml_text)

    items = []
    for elem in root.iter():
        if localname(elem.tag) != "item":
            continue
        title = ""
        desc = ""
        link = ""
        transcripts: list[tuple[str, str]] = []
        for child in list(elem):
            ln = localname(child.tag)
            if ln == "title" and child.text:
                title = child.text.strip()
            elif ln in ("description", "summary") and (child.text or len(child)):
                raw = child.text or "".join(child.itertext())
                if len(raw) > len(desc):
                    desc = raw
            elif ln == "link" and (child.text or child.get("href")):
                link = (child.text or child.get("href") or "").strip()
            elif ln == "transcript":
                # Only Podcasting 2.0 podcast:transcript (avoid random "transcript" links in notes)
                u = child.get("url") or ""
                t = child.get("type") or "text/plain"
                if u:
                    transcripts.append((u, t))
            elif ln == "encoded":  # content:encoded
                raw = child.text or ""
                if len(raw) > len(desc):
                    desc = raw
        if title:
            items.append(
                {
                    "title": title,
                    "norm": normalize_title(title),
                    "desc": strip_html(desc),
                    "link": link,
                    "transcripts": transcripts,
                }
            )
    return items


def fetch_transcript_text(url: str, mime: str) -> str:
    try:
        raw = http_get_text(url, accept=mime or "*/*")
    except Exception as exc:  # noqa: BLE001
        print(f"    transcript fetch fail {url}: {exc}")
        return ""
    mime = (mime or "").lower()
    if "json" in mime:
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "segments" in data:
                return " ".join(
                    str(s.get("body") or s.get("text") or "") for s in data["segments"]
                ).strip()
            if isinstance(data, list):
                return " ".join(
                    str(s.get("body") or s.get("text") or s) for s in data
                ).strip()
        except json.JSONDecodeError:
            pass
    if "vtt" in mime or url.lower().endswith(".vtt"):
        lines = []
        for line in raw.splitlines():
            if not line.strip() or line.startswith("WEBVTT") or "-->" in line or line.strip().isdigit():
                continue
            lines.append(line.strip())
        return " ".join(lines)
    if "srt" in mime or "subrip" in mime or url.lower().endswith(".srt"):
        lines = []
        for line in raw.splitlines():
            if not line.strip() or "-->" in line or line.strip().isdigit():
                continue
            lines.append(line.strip())
        return " ".join(lines)
    return strip_html(raw)


def match_feed_item(norm_title: str, by_norm: dict[str, dict]) -> dict | None:
    if not norm_title:
        return None
    if norm_title in by_norm:
        return by_norm[norm_title]
    # Prefix / containment for truncated titles
    for k, item in by_norm.items():
        if len(norm_title) >= 20 and (norm_title in k or k in norm_title):
            return item
    return None


def enrich_notes(episodes: list[dict], podcasts: list[dict]) -> tuple[dict, dict]:
    top = sorted(podcasts, key=lambda p: p.get("n", 0), reverse=True)[:TOP_PODCASTS_FOR_RSS]
    # podcast → norm_title → [episode indexes] (listened only)
    by_show_norm: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for i, ep in enumerate(episodes):
        name = ep.get("p") or ""
        norm = normalize_title(ep.get("e") or "")
        if name and norm:
            by_show_norm[name][norm].append(i)

    notes: dict[str, dict] = {}
    stats = {
        "podcastsTried": 0,
        "feedsResolved": 0,
        "episodesMatched": 0,
        "withDescription": 0,
        "withTranscript": 0,
        "errors": [],
    }

    for pod in top:
        name = pod["p"]
        stats["podcastsTried"] += 1
        print(f"[{stats['podcastsTried']}/{len(top)}] {name}", flush=True)
        listened = by_show_norm.get(name) or {}
        if not listened:
            continue
        try:
            feed = itunes_feed_url(name)
            time.sleep(0.25)
            if not feed:
                stats["errors"].append(f"no feed: {name}")
                print("  no feed", flush=True)
                continue
            stats["feedsResolved"] += 1
            xml_text = http_get_text(
                feed, accept="application/rss+xml, application/xml, text/xml, */*"
            )
            time.sleep(0.15)
            items = parse_rss_items(xml_text)
            print(f"  feed items={len(items)} listened_titles={len(listened)}", flush=True)

            matched_idxs: set[int] = set()
            transcript_budget = MAX_TRANSCRIPTS_PER_SHOW

            for item in items:
                idxs = listened.get(item["norm"]) or []
                if not idxs:
                    # cheap containment only for longer titles
                    nt = item["norm"]
                    if len(nt) >= 28:
                        for ln, ep_idxs in listened.items():
                            if nt in ln or ln in nt:
                                idxs = ep_idxs
                                break
                if not idxs:
                    continue

                text = ""
                src = "show-notes"
                url = item.get("link") or ""

                if transcript_budget > 0 and item.get("transcripts"):
                    for turl, ttype in item["transcripts"]:
                        tx = fetch_transcript_text(turl, ttype)
                        time.sleep(0.1)
                        if tx and len(tx) > 80:
                            text = tx[:MAX_TRANSCRIPT_CHARS]
                            src = "transcript"
                            url = turl
                            transcript_budget -= 1
                            stats["withTranscript"] += 1
                            break

                if not text and item.get("desc"):
                    text = item["desc"][:MAX_NOTE_CHARS]
                    src = "show-notes"
                    stats["withDescription"] += 1

                if not text:
                    continue

                for idx in idxs:
                    if idx in matched_idxs:
                        continue
                    matched_idxs.add(idx)
                    stats["episodesMatched"] += 1
                    notes[str(idx)] = {
                        "src": src,
                        "text": text,
                        "url": url or None,
                        "p": name,
                        "e": episodes[idx].get("e"),
                    }
            print(f"  matched={len(matched_idxs)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            msg = f"{name}: {exc}"
            print(f"  ERROR {msg}", flush=True)
            stats["errors"].append(msg)

    stats["notesStored"] = len(notes)
    return notes, stats


def main() -> None:
    episodes = json.loads((TABLES / "episodes.json").read_text(encoding="utf-8"))
    podcasts = json.loads((TABLES / "podcasts.json").read_text(encoding="utf-8"))
    print(f"episodes={len(episodes)} podcasts={len(podcasts)}")

    tagged, themes_doc = tag_episodes(episodes)
    (TABLES / "episode-themes.json").write_text(
        json.dumps(tagged, separators=(",", ":")), encoding="utf-8"
    )
    (TABLES / "themes.json").write_text(
        json.dumps(themes_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"themes: {themes_doc['meta']['episodesWithTheme']}/{len(episodes)} tagged; "
        f"top={[t['id']+':'+str(t['count']) for t in themes_doc['themes'][:5]]}"
    )

    notes, stats = enrich_notes(episodes, podcasts)
    (TABLES / "notes.json").write_text(
        json.dumps(notes, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    (TABLES / "notes-meta.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"notes: stored={stats['notesStored']} matched={stats['episodesMatched']} "
        f"desc={stats['withDescription']} transcript={stats['withTranscript']}"
    )


if __name__ == "__main__":
    main()
