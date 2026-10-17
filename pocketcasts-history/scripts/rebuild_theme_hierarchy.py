#!/usr/bin/env python3
"""Rebuild themes.json + episode-themes.json — flat ~100-theme taxonomy.

Evidence priority per episode (strict):
  1. Full transcript (transcript / stt / youtube store)
  2. Episode notes / show notes
  3. Title + show name
  Topic matching uses the best available source only (not a noisy blend).

Other rules:
  - Flat, one click; no parent/child.
  - Local themes are always specific (never bare countries).
  - Geo cues + title actors still come from title/show (and show priors).
  - Noisy domains need multiple hits in long transcripts to avoid spray.
  - Show priors baseline known coverage (A Hora → BR politics; Braincast → tech/culture).
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "tables"

# ---------------------------------------------------------------------------
# Geo cues — title / show / safe folder only
# ---------------------------------------------------------------------------
GEO: dict[str, list[str]] = {
    "br": [
        r"\bbrasil\b", r"\bbrazil\b", r"\bbrasileir", r"\bbolsonar",
        r"\blula\b", r"\blulinha\b", r"\bstf\b", r"\btse\b", r"\bstj\b",
        r"\bplanalto\b", r"\bbras[ií]lia\b", r"\bmoraes\b", r"\bxand[aã]o\b",
        r"\bfachin\b", r"\btoffoli\b", r"\bkassio\b", r"\bgilmar\b",
        r"\btarc[ií]sio\b", r"\bhaddad\b", r"\bhugo motta\b", r"\balcolumbre\b",
        r"\bdatafolha\b", r"\bfl[aá]vio\b", r"\bpetismo\b", r"\bantipetismo\b",
        r"\bcongresso nacional\b", r"\bc[aâ]mara dos deputados\b",
        r"\bsenado federal\b", r"\bsupremo\b",
    ],
    "au": [
        r"\baustralia\b", r"\baustralian\b", r"\balbanese\b", r"\balbo\b",
        r"\bdutton\b", r"\bcanberra\b", r"\bqueensland\b", r"\bnsw\b",
        r"\bvictoria\b", r"\bsydney\b", r"\bmelbourne\b", r"\bone nation\b",
        r"\bpauline hanson\b", r"\baustralian politics\b", r"\bpolitics now\b",
        r"\babc news\b", r"\brobodebt\b", r"\bnacc\b", r"\bpenny wong\b",
    ],
    "us": [
        r"\bunited states\b", r"\bu\.s\.a\.\b", r"\bu\.s\.\b", r"\btrump\b",
        r"\bbiden\b", r"\bharris\b", r"\bkamala\b", r"\bobama\b",
        r"\bwhite house\b", r"\bwashington\b", r"\bcongress\b", r"\bscotus\b",
        r"\bmaga\b", r"\bgop\b", r"\bpentagon\b", r"\bcapitol\b",
        r"\bcapit[oó]lio\b", r"\bfbi\b", r"\bvance\b", r"\bhegseth\b",
    ],
    "eu": [
        r"\beurope\b", r"\beuropean\b", r"\beu\b", r"\bfrance\b", r"\bfran[cç]a\b",
        r"\bmacron\b", r"\bgermany\b", r"\balemanha\b", r"\bscholz\b",
        r"\bmerkel\b", r"\buk\b", r"\bbritain\b", r"\bunited kingdom\b",
        r"\bbrexit\b", r"\bstarmer\b", r"\bspain\b", r"\bespanha\b",
        r"\bitaly\b", r"\bitalia\b", r"\bmeloni\b", r"\bnetherlands\b",
        r"\bsweden\b", r"\bpoland\b", r"\bhungary\b", r"\bhungria\b",
        r"\borb[aá]n\b", r"\bportugal\b", r"\bbrussels\b", r"\bafd\b",
        r"\ble pen\b",
    ],
    "apac": [
        r"\bmalaysia\b", r"\bmalaysian\b", r"\banwar\b", r"\bsingapore\b",
        r"\bindonesia\b", r"\bjakarta\b", r"\bthailand\b", r"\bvietnam\b",
        r"\bphilippines\b", r"\basean\b", r"\bsoutheast asia\b",
        r"\bsouth[- ]east asia\b", r"\basia[- ]pacific\b", r"\bpakistan\b",
        r"\bbangladesh\b",
    ],
    "india": [
        r"\bindia\b", r"\bindian\b", r"\bmodi\b", r"\bdelhi\b", r"\bbjp\b",
        r"\bkongress\b", r"\bkashmir\b",
    ],
    "jp_kr": [
        r"\bjapan\b", r"\bjapanese\b", r"\btokyo\b", r"\bkorea\b",
        r"\bkorean\b", r"\bseoul\b", r"\bkim jong\b", r"\bnorth korea\b",
    ],
    "cn_tw": [
        r"\bchina\b", r"\bchinese\b", r"\bbeijing\b", r"\bxi jinping\b",
        r"\btaiwan\b", r"\btaipei\b", r"\bhong kong\b",
    ],
    "indopac": [
        r"\bindo[- ]pacific\b", r"\baukus\b", r"\bquad\b",
        r"\bsouth china sea\b", r"\bfreedom of navigation\b",
    ],
    "israel_gaza": [
        r"\bisrael\b", r"\bisraeli\b", r"\bgaza\b", r"\bpalestinian\b",
        r"\bpalestina\b", r"\bhamas\b", r"\bnetanyahu\b", r"\bwest bank\b",
        r"\bidf\b", r"\bhezbollah\b", r"\blebanon\b",
    ],
    "iran": [r"\biran\b", r"\btehran\b", r"\bkhamenei\b", r"\birgc\b"],
    "me_other": [
        r"\bsaudi\b", r"\bmiddle east\b", r"\bqatar\b", r"\bsyria\b",
        r"\byemen\b", r"\bhouthis\b", r"\biraq\b",
    ],
    "ukraine": [
        r"\bukraine\b", r"\bukrainian\b", r"\bzelensky\b", r"\bkyiv\b",
        r"\bkiev\b", r"\bdonbas\b", r"\bcrimea\b",
    ],
    "russia": [
        r"\brussia\b", r"\brussian\b", r"\bputin\b", r"\bmoscow\b",
        r"\bkremlin\b",
    ],
    "latam": [
        r"\bargentina\b", r"\bchile\b", r"\bcolombia\b", r"\bvenezuela\b",
        r"\bmexico\b", r"\bm[eé]xico\b", r"\bperu\b", r"\bbolivia\b",
        r"\becuador\b", r"\buruguay\b", r"\bparaguay\b", r"\bcuba\b",
        r"\bmaduro\b", r"\bmilei\b", r"\bboric\b", r"\bpetro\b",
        r"\bamlo\b", r"\blatin america\b", r"\bam[eé]rica latina\b",
    ],
    "af": [
        r"\bafrica\b", r"\bafrican\b", r"\bnigeria\b", r"\bkenya\b",
        r"\bsouth africa\b", r"\bethiopia\b", r"\bsahel\b", r"\bsudan\b",
    ],
}

# Topic pattern banks
ELEC = [
    r"\beleições\b", r"\beleição\b", r"\beleic[oõ]es\b", r"\beleic[aã]o\b",
    r"\belection\b", r"\belectoral\b", r"\bvoto\b", r"\bvota[cç]",
    r"\bvoting\b", r"\bballot\b", r"\burnas\b", r"\bcandidato\b",
    r"\bcandidate\b", r"\bcampanha\b", r"\bcampaign\b", r"\bprim[aá]rias\b",
    r"\bprimary\b", r"\brunoff\b", r"\bsegundo turno\b", r"\bpolls?\b",
    r"\bpesquisa(s)?\b", r"\bindecisos\b", r"\beleitor",
]
GOV = [
    r"\bgoverno\b", r"\bgovernment\b", r"\bminist[eé]rio\b", r"\bministros?\b",
    r"\bminister\b", r"\bcabinet\b", r"\bcongresso\b", r"\bparliament\b",
    r"\bsenado\b", r"\bsenate\b", r"\bc[aâ]mara\b", r"\bplanalto\b",
    r"\bexecutivo\b", r"\bcasa branca\b", r"\bwhite house\b", r"\blegislat",
    r"\bemendas?\b", r"\bcentr[aã]o\b", r"\baren[aã]o\b",
]
COURT = [
    r"\bstf\b", r"\btse\b", r"\bstj\b", r"\bsupremo\b", r"\bsupreme court\b",
    r"\bscotus\b", r"\bjudici[aá]rio\b", r"\bjudiciary\b", r"\btribunal\b",
    r"\bcourt\b", r"\binqu[eé]rito\b", r"\bimpeachment\b", r"\bfachin\b",
    r"\btoffoli\b", r"\bmoraes\b", r"\bkassio\b", r"\bgilmar\b",
    r"\bdelação\b", r"\bdelatores?\b",
]
MEDIA = [
    r"\bm[ií]dia\b", r"\bmedia\b", r"\bimprensa\b", r"\bpress\b",
    r"\bjornalismo\b", r"\bjournalis", r"\brede social\b", r"\bsocial media\b",
    r"\btwitter\b", r"\bfacebook\b", r"\bmeta\b", r"\bcensura\b",
    r"\bcensorship\b", r"\bdesinforma", r"\bdisinfo", r"\bfake news\b",
    r"\bdeep ?fake\b", r"\bbig techs?\b",
]
ECON = [
    r"\beconomia\b", r"\beconomy\b", r"\binfla[cç]", r"\binflation\b",
    r"\bjuros\b", r"\binterest rate\b", r"\bmercado\b", r"\bmarkets\b",
    r"\bgdp\b", r"\bpib\b", r"\bbolsa\b", r"\bstocks\b", r"\btarifa\b",
    r"\btariff\b", r"\bcom[eé]rcio\b", r"\btrade\b", r"\bdesemprego\b",
    r"\bunemployment\b", r"\bbanco central\b", r"\bfederal reserve\b",
    r"\brecess", r"\bor[cç]amento\b", r"\bbudget\b", r"\bd[oó]lares?\b",
]
CRIME = [
    r"\bcrime\b", r"\bpol[ií]cia\b", r"\bpolice\b", r"\bhomic[ií]dio\b",
    r"\bmurder\b", r"\btr[aá]fico\b", r"\bcorrup[cç]", r"\bcorruption\b",
    r"\bpris[aã]o\b", r"\bprison\b", r"\btiroteio\b", r"\bviol[eê]ncia\b",
    r"\bpf\b", r"\bpol[ií]cia federal\b",
]
DEF = [
    r"\bguerra\b", r"\bwars?\b", r"\bmilitary\b", r"\bmilitar\b",
    r"\bdefence\b", r"\bdefense\b", r"\bnato\b", r"\botan\b",
    r"\bmissile\b", r"\bairstrike\b", r"\bfor[cç]as armadas\b",
    r"\bpentagon\b", r"\bsoldiers?\b", r"\bfuzis?\b", r"\bmetralhadora\b",
    r"\barmed forces\b", r"\bbattlefield\b", r"\binvasion\b",
]
CLIM = [
    r"\bclima\b", r"\bclimate\b", r"\baquecimento global\b",
    r"\bglobal warming\b", r"\bcarbon\b", r"\bemiss[oõ]es\b", r"\bemissions\b",
    r"\bpetr[oó]leo\b", r"\boil\b", r"\bcarv[aã]o\b", r"\bcoal\b",
    r"\brenov[aá]vel\b", r"\brenewable\b", r"\bamaz[oô]nia\b",
    r"\bdesmatamento\b",
]
MIG = [
    r"\bimigra", r"\bmigra[cç]", r"\bmigration\b", r"\brefugiad",
    r"\brefugee\b", r"\basylum\b", r"\bfronteira\b", r"\bborder\b",
    r"\bdeport", r"\bvisto\b", r"\bvisa\b", r"\bice\b",
]
DIPL = [
    r"\bdiplomacia\b", r"\bdiplomacy\b", r"\bforeign policy\b",
    r"\bpol[ií]tica externa\b", r"\bonu\b", r"\bg20\b", r"\bembaixad",
    r"\bambassador\b", r"\bsanctions\b", r"\bsan[cç][oõ]es\b",
]
WAR = [
    r"\bguerra\b", r"\bwar\b", r"\binvasion\b", r"\binvas[aã]o\b",
    r"\boffensive\b", r"\bbattlefield\b", r"\bairstrike\b", r"\bmissile\b",
    r"\bceasefire\b", r"\btr[eé]gua\b", r"\bstrait\b",
]
AI = [
    r"\bai\b", r"\bartificial intelligence\b", r"\bintelig[eê]ncia artificial\b",
    r"\bchatgpt\b", r"\bopenai\b", r"\bmachine learning\b", r"\bllm\b",
    r"\balgoritmo\b", r"\balgorithm\b", r"\bagentes? aut[oô]nom",
]
PLATFORMS = [
    r"\btwitter\b", r"\bfacebook\b", r"\binstagram\b", r"\btiktok\b",
    r"\brede social\b", r"\bsocial media\b", r"\bdiscord\b", r"\bwhatsapp\b",
    r"\bmeta\b", r"\byoutube\b", r"\bbig techs?\b", r"\bplataforma",
]
ADVERTISING = [
    r"\bpublicidade\b", r"\badvertis", r"\bag[eê]ncia\b", r"\bmarketing\b",
    r"\bbranding\b", r"\ban[uú]ncio\b", r"\badtech\b", r"\bmarcas?\b",
]
HOUSING = [
    r"\bhousing\b", r"\baluguel\b", r"\bmortgage\b", r"\bimobili",
    r"\bcost of living\b", r"\bcusto de vida\b", r"\brenda\b",
]
LABOR = [
    r"\bsindicato\b", r"\bunion\b", r"\bstrike\b", r"\bgreve\b",
    r"\bwage\b", r"\bsal[aá]rio\b", r"\btrabalhista\b", r"\b6\s*x\s*1\b",
    r"\b6 por 1\b",
]
NUCLEAR = [r"\bnuclear\b", r"\buranium\b", r"\biaea\b"]
CYBER = [
    r"\bcyber\b", r"\bhacker\b", r"\bransomware\b", r"\bespionage\b",
    r"\bespionagem\b",
]
PANDEMIC = [
    r"\bcovid\b", r"\bpandemia\b", r"\bpandemic\b", r"\bvacina\b",
    r"\bvaccine\b",
]
FILM = [
    r"\bfilme\b", r"\bfilm\b", r"\bcinema\b", r"\boscar\b", r"\bnetflix\b",
    r"\bs[eé]rie\b", r"\btv show\b", r"\bgame of thrones\b",
]
MUSIC = [
    r"\bm[uú]sica\b", r"\bmusic\b", r"\balbum\b", r"\bspotify\b",
    r"\bsongwriter\b", r"\bcantor\b", r"\bcantora\b", r"\bconcert\b",
    r"\bshow musical\b",
]
FOOTBALL = [
    r"\bfutebol\b", r"\bfootball\b", r"\bsoccer\b", r"\bcopa\b",
    r"\bworld cup\b", r"\bpremier league\b", r"\bmundial\b",
]
PHILOSOPHY = [
    r"\bfilosofia\b", r"\bphilosophy\b", r"\b[eé]tica\b", r"\bethics\b",
]
PSYCH = [
    r"\bpsicologia\b", r"\bpsychology\b", r"\bmental health\b",
    r"\bsa[uú]de mental\b", r"\bcomportamento\b", r"\bbehaviou?r\b",
]

# Title actors → local themes. Each rule is (geo_key|None, pattern, theme_ids).
# geo_key required in title/show (or Brazilian/US/AU politics show) before firing —
# prevents “segundo turno” in Ecuador or “Lula na ONU” becoming Brazilian elections.
TITLE_ACTORS: list[tuple[str | None, str, list[str]]] = [
    # Brazil — elections (campaign language; not bare Lula)
    (
        "br",
        r"\b(bolsonar|fl[aá]vio bolsonar|tarc[ií]sio|haddad|candidato|"
        r"campanha|pesquisa(s)?|eleitor|indecisos|petismo|antipetismo|"
        r"segundo turno|elei[cç])\b",
        ["br-elections", "br-government"],
    ),
    # Brazil — Lula alone is government/politics, not automatically elections
    ("br", r"\b(lula|lulinha)\b", ["br-government"]),
    # Brazil — courts
    (
        "br",
        r"\b(stf|tse|stj|supremo|fachin|toffoli|moraes|kassio|gilmar|"
        r"xand[aã]o|delação|inqu[eé]rito)\b",
        ["br-courts", "br-government"],
    ),
    # Brazil — congress / executive
    (
        "br",
        r"\b(ministros?|congresso|senado|c[aâ]mara|planalto|hugo motta|"
        r"alcolumbre|emendas?|centr[aã]o|aren[aã]o|governo|"
        r"(?<![a-z])pl(?![a-z])|(?<![a-z])pt(?![a-z]))\b",
        ["br-government"],
    ),
    # US
    (
        "us",
        r"\b(trump|biden|harris|kamala|maga|vance|hegseth)\b",
        ["us-elections", "us-government"],
    ),
    (
        "us",
        r"\b(scotus|supreme court|white house|capitol|capit[oó]lio)\b",
        ["us-government", "us-courts"],
    ),
    # Australia
    (
        "au",
        r"\b(albanese|albo|dutton|one nation|pauline hanson)\b",
        ["au-elections", "au-government"],
    ),
]

# Shows that imply a geo even when the title is witty / actor-only
SHOW_GEO: dict[str, str] = {
    "a hora": "br",
    "foro de teresina": "br",
    "o assunto": "br",
    "boletim folha": "br",
    "durma com essa": "br",
    "australian politics": "au",
    "politics now": "au",
    "democracy sausage with mark kenny": "au",
    "7am": "au",
    "abc news daily": "au",
    "the morning edition": "au",
    "up first from npr": "us",
    "the daily": "us",
}

# Show baselines — applied to every episode of that show (title-first world).
# Keys matched case-insensitively against podcast name.
SHOW_DEFAULTS: dict[str, list[str]] = {
    "a hora": ["br-government", "br-elections"],
    "foro de teresina": ["br-government", "br-elections"],
    "o assunto": ["br-government"],
    "boletim folha": ["br-government"],
    "durma com essa": ["br-government"],
    "braincast": ["digital-culture", "ai-technology", "advertising-marketing"],
    "nerdcast": ["culture-entertainment", "digital-culture"],
    "cinemático": ["film-tv"],
    "cinematico": ["film-tv"],
    "hidden brain": ["psychology-behaviour", "ideas-society"],
    "the ezra klein show": ["ideas-society", "us-government"],
    "australian politics": ["au-government", "au-elections"],
    "politics now": ["au-government", "au-elections"],
    "democracy sausage with mark kenny": ["au-government", "au-elections"],
    "7am": ["au-government"],
    "abc news daily": ["au-government"],
    "the morning edition": ["au-government"],
    "up first from npr": ["us-government"],
    "the daily": ["us-government"],
    "xadrez verbal": ["diplomacy", "history", "international-affairs"],
    "petit journal": ["international-affairs", "diplomacy"],
    "lowy institute": ["diplomacy", "indo-pacific-security"],
    "the national security podcast": ["defence-war", "indo-pacific-security"],
    "aspi podcast: policy, guns & money": ["defence-war", "indo-pacific-security"],
    "asia geopolitics": ["indo-pacific-security", "diplomacy"],
    "beyond the ballot box": ["apac-elections", "apac-government"],
    "straight talk southeast asia": ["apac-government", "diplomacy"],
    "global roaming with geraldine doogue and hamish macdonald": [
        "international-affairs",
        "diplomacy",
    ],
}

# min_hits: for long primary text (transcript), require this many pattern hits
# to reduce single-mention spray. Short text (title/notes) always uses 1.
def T(id: str, name: str, kind: str, blurb: str, *, geo=None, topic=None, min_hits=1):
    return {
        "id": id,
        "name": name,
        "kind": kind,
        "blurb": blurb,
        "geo": geo,
        "topic": topic,
        "min_hits": min_hits,
    }


THEMES: list[dict] = [
    # ---- Brazil locals ----
    T("br-elections", "Brazilian elections", "local", "Elections and campaigns in Brazil.", geo="br", topic=ELEC),
    T("br-government", "Brazilian government", "local", "Brazilian executive, ministries, Congress.", geo="br", topic=GOV),
    T("br-courts", "Brazilian courts", "local", "STF, TSE, and Brazilian judicial politics.", geo="br", topic=COURT),
    T("br-media", "Brazilian media", "local", "Press, platforms, and media politics in Brazil.", geo="br", topic=MEDIA),
    T("br-economy", "Brazilian economy", "local", "Brazilian markets, inflation, fiscal policy.", geo="br", topic=ECON),
    T("br-crime", "Brazilian crime & security", "local", "Crime and security in Brazil.", geo="br", topic=CRIME, min_hits=2),
    T("br-climate", "Brazilian climate & Amazon", "local", "Climate, Amazon, and energy in Brazil.", geo="br", topic=CLIM),
    T("br-health", "Brazilian health policy", "local", "Public health and SUS politics in Brazil.", geo="br", topic=[r"\bsa[uú]de\b", r"\bsus\b", r"\bcovid\b", r"\bvacina\b", r"\bhospital\b"]),
    # ---- Australia locals ----
    T("au-elections", "Australian elections", "local", "Federal and state elections in Australia.", geo="au", topic=ELEC),
    T("au-government", "Australian government", "local", "Australian government and parliament.", geo="au", topic=GOV),
    T("au-economy", "Australian economy", "local", "Australian economy, rates, budgets.", geo="au", topic=ECON),
    T("au-climate", "Australian climate & energy", "local", "Climate and energy policy in Australia.", geo="au", topic=CLIM),
    T("au-defence", "Australian defence", "local", "Australian defence and AUKUS politics.", geo="au", topic=DEF + [r"\baukus\b", r"\badf\b"]),
    T("au-media", "Australian media", "local", "Australian media and press politics.", geo="au", topic=MEDIA),
    T("au-immigration", "Australian immigration", "local", "Australian immigration and borders.", geo="au", topic=MIG),
    # ---- US locals ----
    T("us-elections", "US elections", "local", "US elections and campaigns.", geo="us", topic=ELEC),
    T("us-government", "US government", "local", "US White House, Congress, federal government.", geo="us", topic=GOV),
    T("us-courts", "US courts", "local", "SCOTUS and US courts.", geo="us", topic=COURT),
    T("us-economy", "US economy", "local", "US economy, Fed, markets.", geo="us", topic=ECON),
    T("us-immigration", "US immigration", "local", "US immigration and ICE.", geo="us", topic=MIG),
    T("us-foreign-policy", "US foreign policy", "local", "US foreign policy and diplomacy.", geo="us", topic=DIPL),
    T("us-defence", "US defence", "local", "US military and Pentagon.", geo="us", topic=DEF),
    T("us-climate", "US climate & energy", "local", "US climate and energy policy.", geo="us", topic=CLIM),
    T("us-health", "US health policy", "local", "US health policy and public health.", geo="us", topic=[r"\bhealth\b", r"\bcovid\b", r"\bvaccine\b", r"\bmedicare\b", r"\bcdc\b"]),
    T("us-media", "US media", "local", "US media and platform politics.", geo="us", topic=MEDIA),
    T("us-crime", "US crime & policing", "local", "US crime and policing.", geo="us", topic=CRIME, min_hits=2),
    # ---- Regional locals ----
    T("eu-elections", "European elections", "local", "Elections across Europe.", geo="eu", topic=ELEC),
    T("eu-government", "European government", "local", "European governments and EU institutions.", geo="eu", topic=GOV),
    T("latam-elections", "Latin American elections", "local", "Elections in Latin America (ex-Brazil).", geo="latam", topic=ELEC),
    T("latam-government", "Latin American government", "local", "Governments in Latin America (ex-Brazil).", geo="latam", topic=GOV),
    T("apac-elections", "Asia-Pacific elections", "local", "Elections across Asia-Pacific (ex CN/AU/US/IN).", geo="apac", topic=ELEC),
    T("apac-government", "Asia-Pacific government", "local", "Governments across Asia-Pacific (ex CN/AU/US/IN).", geo="apac", topic=GOV),
    T("india-elections", "Indian elections", "local", "Elections in India.", geo="india", topic=ELEC),
    T("india-government", "Indian government", "local", "Indian government and BJP/Congress politics.", geo="india", topic=GOV),
    T("japan-korea-security", "Japan & Korea security", "local", "Japan/Korea security and North Korea.", geo="jp_kr", topic=DEF + WAR + GOV),
    T("af-elections", "African elections", "local", "Elections across Africa.", geo="af", topic=ELEC),
    T("af-government", "African government", "local", "Governments across Africa.", geo="af", topic=GOV),
    T("cn-government", "Chinese government", "local", "Chinese state and CCP politics.", geo="cn_tw", topic=GOV),
    T("me-government", "Middle East government", "local", "Middle East governments (ex Israel–Gaza).", geo="me_other", topic=GOV),
    T("ru-government", "Russian government", "local", "Russian government and Kremlin.", geo="russia", topic=GOV),
    # ---- Storylines ----
    T("israel-gaza-war", "Israel–Gaza war", "story", "Israel–Gaza war coverage.", geo="israel_gaza"),
    T("ukraine-war", "Ukraine war", "story", "Russia’s war against Ukraine.", geo="ukraine"),
    T("china-taiwan", "China–Taiwan tensions", "story", "China–Taiwan cross-strait tensions.", geo="cn_tw", topic=WAR + [r"\btaiwan\b", r"\btaipei\b", r"\bstrait\b"]),
    T("indo-pacific-security", "Indo-Pacific security", "story", "AUKUS, Quad, Indo-Pacific security.", geo="indopac"),
    T("iran-conflict", "Iran conflict", "story", "Iran conflict, nuclear, and regional proxy wars.", geo="iran"),
    # ---- Frames ----
    T("extreme-right", "Extreme right", "frame", "Far-right and extreme-right movements.", topic=[
        r"\bextrema[- ]?direita\b", r"\bfar[- ]?right\b", r"\balt[- ]?right\b",
        r"\bdireita radical\b", r"\bneonazi\b", r"\bneo[- ]?nazi\b", r"\bfascis",
        r"\bbolsonarismo\b",
    ]),
    T("populism", "Populism", "frame", "Populist politics.", topic=[r"\bpopulist\b", r"\bpopulismo\b", r"\bpopulism\b"]),
    T("authoritarianism", "Authoritarianism", "frame", "Authoritarian and illiberal politics.", topic=[
        r"\bautoritar", r"\bauthoritarian\b", r"\bditadura\b", r"\bdictatorship\b",
        r"\bautocrat", r"\billiberal\b", r"\bgolpe\b", r"\bcoup\b",
    ]),
    T("feminism-gender", "Feminism & gender", "frame", "Feminism, abortion, women’s rights.", topic=[
        r"\bfeminis", r"\bg[eê]nero\b", r"\bgender\b", r"\baborto\b", r"\babortion\b",
        r"\bmisogyn", r"\bwomen'?s rights\b", r"\bdireitos? das mulheres\b", r"\bvoto feminino\b",
    ]),
    T("lgbtq", "LGBTQ+", "frame", "LGBTQ+ rights and culture.", topic=[
        r"\blgbt", r"\btransg[eê]nero\b", r"\btransgender\b", r"\bqueer\b",
    ]),
    T("human-rights", "Human rights", "frame", "Human rights and civil liberties.", topic=[
        r"\bdireitos? humanos?\b", r"\bhuman rights\b", r"\bamnesty\b",
        r"\btortura\b", r"\btorture\b", r"\bliberdade de express",
        r"\bfreedom of (speech|expression)\b",
    ]),
    T("race", "Race & racism", "frame", "Race and racism.", topic=[
        r"\bracis", r"\bracial\b", r"\bnegro\b", r"\bblack lives\b", r"\bcotas raciais\b",
    ]),
    T("indigenous", "Indigenous rights", "frame", "Indigenous and First Nations rights.", topic=[
        r"\bind[ií]gena\b", r"\bindigenous\b", r"\bquilombola\b",
        r"\bfirst nations\b", r"\bnative title\b",
    ]),
    # ---- Domains (noisy ones use higher min_hits on long transcripts) ----
    T("economy-markets", "Economy & markets", "domain", "Economy, markets, inflation, trade.", topic=ECON),
    T("housing-cost-of-living", "Housing & cost of living", "domain", "Housing and cost of living.", topic=HOUSING, min_hits=2),
    T("labor-unions", "Labor & unions", "domain", "Labor, wages, strikes, unions.", topic=LABOR, min_hits=2),
    T("defence-war", "Defence & war", "domain", "Military conflict and defence.", topic=DEF, min_hits=3),
    T("nuclear", "Nuclear", "domain", "Nuclear weapons and energy.", topic=NUCLEAR, min_hits=2),
    T("cyber-intelligence", "Cyber & intelligence", "domain", "Cybersecurity and espionage.", topic=CYBER, min_hits=2),
    T("climate-energy", "Climate & energy", "domain", "Climate policy and energy.", topic=CLIM),
    T("ai-technology", "Artificial intelligence", "domain", "AI, LLMs, and machine learning.", topic=AI),
    T("social-platforms", "Social media & platforms", "domain", "Social platforms and big tech.", topic=PLATFORMS, min_hits=2),
    T("advertising-marketing", "Advertising & marketing", "domain", "Advertising, agencies, and brands.", topic=ADVERTISING, min_hits=2),
    T("digital-culture", "Digital culture", "domain", "Digital culture, internet behaviour, creative tech.", topic=[
        r"\bcultura digital\b", r"\bdigital culture\b", r"\binternet\b",
        r"\btecnologia\b", r"\btechnology\b", r"\binova[cç]", r"\binnovation\b",
        r"\bcomportamento\b", r"\bcriativ",
    ], min_hits=2),
    T("pandemics-vaccines", "Pandemics & vaccines", "domain", "Pandemics and vaccines.", topic=PANDEMIC),
    T("health-medicine", "Health & medicine", "domain", "Health and medicine.", topic=[
        r"\bsa[uú]de\b", r"\bhealth\b", r"\bhospital\b", r"\bm[eé]dic", r"\bmedicine\b",
    ], min_hits=2),
    T("science", "Science", "domain", "Science and research.", topic=[
        r"\bcient[ií]fic", r"\bscience\b", r"\bresearch\b", r"\bpesquisa cient",
    ], min_hits=2),
    T("diplomacy", "Diplomacy", "domain", "Diplomacy and foreign policy.", topic=DIPL),
    T("international-affairs", "International affairs", "domain", "Geopolitics and world affairs.", topic=[
        r"\bgeopolitic", r"\binternational affairs\b", r"\brelações internacionais\b",
        r"\bworld affairs\b",
    ], min_hits=2),
    T("migration-borders", "Migration & borders", "domain", "Migration and borders.", topic=MIG, min_hits=2),
    T("crime-policing", "Crime & policing", "domain", "Crime and policing.", topic=CRIME, min_hits=3),
    T("corruption", "Corruption", "domain", "Corruption and graft scandals.", topic=[
        r"\bcorrup[cç]", r"\bcorruption\b", r"\bgraft\b", r"\bpropina\b",
    ], min_hits=2),
    T("film-tv", "Film & TV", "domain", "Film, TV, and streaming.", topic=FILM, min_hits=2),
    T("music", "Music", "domain", "Music and the music industry.", topic=MUSIC, min_hits=2),
    T("culture-entertainment", "Culture & entertainment", "domain", "Broader culture and entertainment.", topic=[
        r"\bcultura\b", r"\bculture\b", r"\bentertainment\b", r"\bcelebridade\b",
        r"\bfandom\b", r"\bgames?\b", r"\bvideogame\b",
    ], min_hits=2),
    T("football", "Football / soccer", "domain", "Football and World Cup.", topic=FOOTBALL, min_hits=2),
    T("sport", "Sport", "domain", "Sport beyond football.", topic=[
        r"\bolimp[ií]", r"\bolympic", r"\bnba\b", r"\bnfl\b", r"\btennis\b",
        r"\bformula ?1\b", r"\bsport\b", r"\besporte\b",
    ], min_hits=2),
    T("philosophy-ethics", "Philosophy & ethics", "domain", "Philosophy and ethics.", topic=PHILOSOPHY, min_hits=2),
    T("psychology-behaviour", "Psychology & behaviour", "domain", "Psychology and behaviour.", topic=PSYCH, min_hits=2),
    T("ideas-society", "Ideas & society", "domain", "Ideas, society, and everyday life.", topic=[
        r"\bsociedade\b", r"\bsociety\b", r"\brelacionamento\b", r"\brelationship\b",
        r"\bideas?\b", r"\bideias?\b",
    ], min_hits=2),
    T("history", "History", "domain", "History and memory.", topic=[
        r"\bhist[oó]ria\b", r"\bhistory\b", r"\bguerra fria\b", r"\bcold war\b",
        r"\bimp[eé]rio\b", r"\bempire\b", r"\bcolonial\b",
    ], min_hits=2),
    T("press-journalism", "Press & journalism", "domain", "Press and journalism.", topic=[
        r"\bimprensa\b", r"\bpress\b", r"\bjornalismo\b", r"\bjournalis",
        r"\bnewsroom\b",
    ], min_hits=2),
    T("disinformation", "Disinformation", "domain", "Disinformation and fake news.", topic=[
        r"\bdesinforma", r"\bdisinfo", r"\bfake news\b", r"\bmisinforma",
        r"\bdeep ?fake\b",
    ], min_hits=2),
    T("religion", "Religion & belief", "domain", "Religion and belief.", topic=[
        r"\breligion\b", r"\breligi[aã]o\b", r"\bchurch\b", r"\bigreja\b",
        r"\bislam\b", r"\bmuslim\b", r"\bchristian", r"\bevangelical",
    ], min_hits=2),
    T("education", "Education", "domain", "Schools and universities.", topic=[
        r"\beducation\b", r"\beduca[cç]", r"\bschool\b", r"\bescola\b",
        r"\buniversity\b", r"\buniversidade\b", r"\benem\b",
    ], min_hits=2),
    # ---- Extra granularity toward ~100 ----
    T("br-congress", "Brazilian Congress", "local", "Brazilian Chamber, Senate, and amendments.", geo="br", topic=[
        r"\bcongresso\b", r"\bsenado\b", r"\bc[aâ]mara\b", r"\bemendas?\b",
        r"\bhugo motta\b", r"\balcolumbre\b", r"\bcentr[aã]o\b",
    ]),
    T("us-congress", "US Congress", "local", "US House, Senate, and Capitol Hill.", geo="us", topic=[
        r"\bcongress\b", r"\bsenate\b", r"\bhouse of representatives\b",
        r"\bcapitol\b", r"\bcapit[oó]lio\b",
    ]),
    T("trade-tariffs", "Trade & tariffs", "domain", "Trade policy and tariffs.", topic=[
        r"\btarifa\b", r"\btariff\b", r"\bcom[eé]rcio\b", r"\btrade war\b",
        r"\btrade deal\b", r"\bprotecionismo\b", r"\bprotectionism\b",
    ], min_hits=2),
    T("central-banks", "Central banks & rates", "domain", "Central banks and interest rates.", topic=[
        r"\bbanco central\b", r"\bfederal reserve\b", r"\bthe fed\b",
        r"\brba\b", r"\binterest rate\b", r"\bjuros\b", r"\bselic\b",
    ], min_hits=2),
    T("startups-venture", "Startups & venture", "domain", "Startups and venture capital.", topic=[
        r"\bstartup\b", r"\bventure capital\b", r"\bunic[oó]rnio\b",
        r"\bsilicon valley\b", r"\bipo\b",
    ], min_hits=2),
    T("gaming", "Gaming", "domain", "Video games and gaming culture.", topic=[
        r"\bvideogame\b", r"\bvideo game\b", r"\bgaming\b", r"\be-?sport",
        r"\bplaystation\b", r"\bxbox\b", r"\bnintendo\b",
    ], min_hits=2),
    T("books-literature", "Books & literature", "domain", "Books and literature.", topic=[
        r"\blivro\b", r"\bbook\b", r"\bliteratura\b", r"\bliterature\b",
        r"\bnovel\b", r"\bromancista\b", r"\bauthor\b", r"\bescriptor\b",
    ], min_hits=2),
    T("space", "Space", "domain", "Space exploration and satellites.", topic=[
        r"\bnasa\b", r"\bspacex\b", r"\bsatellite\b", r"\bspace\b",
        r"\bespa[cç]o\b", r"\bastronaut",
    ], min_hits=2),
    T("weather-disasters", "Weather & disasters", "domain", "Storms, floods, fires, disasters.", topic=[
        r"\bhurricane\b", r"\bflood", r"\bwildfire\b", r"\bearthquake\b",
        r"\bcyclone\b", r"\benchente", r"\binc[eê]ndio", r"\bdesastre\b",
    ], min_hits=2),
    T("eu-far-right", "European far right", "local", "Far-right parties and politics in Europe.", geo="eu", topic=[
        r"\bfar[- ]?right\b", r"\bextrema[- ]?direita\b", r"\bafd\b",
        r"\ble pen\b", r"\bmeloni\b", r"\borb[aá]n\b", r"\bnational rally\b",
    ]),
    T("venezuela-crisis", "Venezuela crisis", "local", "Venezuela politics and crisis.", geo="latam", topic=[
        r"\bvenezuela\b", r"\bmaduro\b", r"\bguaid[oó]\b",
    ]),
    T("argentina-politics", "Argentine politics", "local", "Argentine politics and Milei.", geo="latam", topic=[
        r"\bargentina\b", r"\bmilei\b", r"\bperon",
    ]),
    T("uk-politics", "UK politics", "local", "UK politics, Brexit, Westminster.", geo="eu", topic=[
        r"\buk\b", r"\bbritain\b", r"\bbrexit\b", r"\bstarmer\b",
        r"\bwestrminster\b", r"\bwestminster\b", r"\btories\b", r"\blabour\b",
    ]),
    T("france-politics", "French politics", "local", "French politics and Macron.", geo="eu", topic=[
        r"\bfrance\b", r"\bfran[cç]a\b", r"\bmacron\b", r"\ble pen\b",
    ]),
    T("germany-politics", "German politics", "local", "German politics and AfD.", geo="eu", topic=[
        r"\bgermany\b", r"\balemanha\b", r"\bscholz\b", r"\bafd\b", r"\bmerkel\b",
    ]),
]


def _compile(pats: list[str] | None) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in (pats or [])]


GEO_RE = {k: _compile(v) for k, v in GEO.items()}
ACTOR_RE = [(geo, re.compile(p, re.I), ids) for geo, p, ids in TITLE_ACTORS]
COMPILED = [
    {
        **t,
        "geo_re": GEO_RE.get(t["geo"] or "", []),
        "topic_re": _compile(t.get("topic")),
    }
    for t in THEMES
]
THEME_IDS = {t["id"] for t in COMPILED}


def match_count(pats: list[re.Pattern], text: str) -> int:
    if not pats or not text:
        return 0
    n = 0
    for p in pats:
        n += len(p.findall(text))
    return n


def matches(pats: list[re.Pattern], text: str, *, min_hits: int = 1, long_text: bool = False) -> bool:
    need = min_hits if long_text and min_hits > 1 else 1
    return match_count(pats, text) >= need


def primary_evidence(
    i: int,
    notes: dict,
    full_texts: dict[str, str],
    title_show: str,
) -> tuple[str, str, bool]:
    """Return (text, src, is_long) with priority: transcript → notes → title/show."""
    tx = full_texts.get(str(i)) or ""
    if tx.strip():
        note = notes.get(str(i)) or {}
        src = note.get("src") if note.get("src") in ("transcript", "stt", "youtube") else "transcript"
        return tx, src or "transcript", len(tx) > 800
    note = notes.get(str(i)) or {}
    nt = (note.get("text") or "").strip()
    if nt:
        return nt, note.get("src") or "notes", len(nt) > 800
    return title_show, "title", False


def show_key(show: str) -> str:
    return (show or "").strip().lower()


def show_defaults(show: str) -> list[str]:
    key = show_key(show)
    if key in SHOW_DEFAULTS:
        return list(SHOW_DEFAULTS[key])
    for k, ids in SHOW_DEFAULTS.items():
        if k in key or key in k:
            return list(ids)
    return []


def show_geo(show: str) -> str | None:
    key = show_key(show)
    if key in SHOW_GEO:
        return SHOW_GEO[key]
    for k, g in SHOW_GEO.items():
        if k in key or key in k:
            return g
    return None


def tag_episode(
    *,
    title_show: str,
    primary: str,
    primary_long: bool,
    show: str,
    geo_hit: dict[str, bool],
) -> list[str]:
    hits: list[str] = []

    def add(tid: str) -> None:
        if tid in THEME_IDS and tid not in hits:
            hits.append(tid)

    # Show can imply geo for actor rules (A Hora titles rarely say “Brasil”)
    sg = show_geo(show)
    if sg:
        geo_hit = dict(geo_hit)
        geo_hit[sg] = True

    # 1) Show baselines (known coverage)
    for tid in show_defaults(show):
        add(tid)

    # 2) Title actors → local compounds (geo-gated; titles carry witty politics cues)
    for gk, cre, ids in ACTOR_RE:
        if gk and not geo_hit.get(gk):
            continue
        if cre.search(title_show):
            for tid in ids:
                add(tid)

    # 3) Local / story — topic match on primary evidence; geo from title/show
    for t in COMPILED:
        if t["kind"] not in ("local", "story"):
            continue
        gk = t["geo"]
        if not gk or not geo_hit.get(gk):
            continue
        if gk == "apac" and (
            geo_hit.get("cn_tw") or geo_hit.get("au") or geo_hit.get("us") or geo_hit.get("india")
        ):
            continue
        topic_re = t["topic_re"]
        if t["kind"] == "story" and not topic_re:
            add(t["id"])
            continue
        if topic_re and matches(
            topic_re, primary, min_hits=t["min_hits"], long_text=primary_long
        ):
            add(t["id"])

    # 4) Frames + domains — primary evidence only
    for t in COMPILED:
        if t["kind"] not in ("frame", "domain"):
            continue
        topic_re = t["topic_re"]
        if not topic_re:
            continue
        if matches(topic_re, primary, min_hits=t["min_hits"], long_text=primary_long):
            add(t["id"])

    return hits


def record_evidence(
    evidence: dict[str, Counter],
    tid: str,
    *,
    src: str,
    primary: str,
    title_show: str,
    topic_re: list[re.Pattern],
    geo_re: list[re.Pattern],
) -> None:
    pats = topic_re or geo_re
    bucket = {
        "transcript": "transcript",
        "stt": "transcript",
        "youtube": "transcript",
        "notes": "notes",
        "show-notes": "notes",
        "title": "title",
    }.get(src, "title")
    if not pats:
        evidence[tid][bucket] += 1
        return
    if matches(pats, primary) or matches(pats, title_show):
        evidence[tid][bucket] += 1
    else:
        evidence[tid][bucket] += 1  # show-default / actor path


def tag_all(
    episodes: list[dict],
    notes: dict,
    full_texts: dict[str, str] | None = None,
) -> tuple[list[list[str]], dict]:
    counts: Counter = Counter()
    samples: dict[str, list] = defaultdict(list)
    by_year: dict[str, Counter] = defaultdict(Counter)
    evidence: dict[str, Counter] = defaultdict(Counter)
    tagged: list[list[str]] = []
    full_texts = full_texts or {}
    theme_by_id = {t["id"]: t for t in COMPILED}
    src_counts: Counter = Counter()

    for i, ep in enumerate(episodes):
        title = ep.get("e") or ""
        show = ep.get("p") or ""
        folder = (ep.get("f") or "").strip()
        safe_folder = ""
        fl = folder.lower()
        if fl in {
            "entertaining",
            "history, geography & culture",
            "good to know",
            "health & science",
            "rights, diversity & inclusion",
        }:
            safe_folder = folder
        title_show = f"{title}\n{show}\n{safe_folder}"
        primary, src, primary_long = primary_evidence(i, notes, full_texts, title_show)
        src_counts[src] += 1
        geo_hit = {k: matches(rs, title_show) for k, rs in GEO_RE.items()}
        hits = tag_episode(
            title_show=title_show,
            primary=primary,
            primary_long=primary_long,
            show=show,
            geo_hit=geo_hit,
        )

        for tid in hits:
            t = theme_by_id[tid]
            counts[tid] += 1
            by_year[tid][str(ep.get("y") or "")] += 1
            record_evidence(
                evidence,
                tid,
                src=src,
                primary=primary,
                title_show=title_show,
                topic_re=t["topic_re"],
                geo_re=t["geo_re"],
            )
            if len(samples[tid]) < 8:
                samples[tid].append(
                    {"i": i, "e": title, "p": show, "d": ep.get("d")}
                )
        tagged.append(hits)

    catalog = []
    for t in COMPILED:
        tid = t["id"]
        ev = dict(evidence.get(tid) or {})
        catalog.append(
            {
                "id": tid,
                "name": t["name"],
                "blurb": t["blurb"],
                "kind": t["kind"],
                "facet": t["kind"],
                "count": int(counts.get(tid, 0)),
                "byYear": dict(sorted(by_year[tid].items())),
                "evidence": {
                    "title": int(ev.get("title", 0)),
                    "notes": int(ev.get("notes", 0)),
                    "transcript": int(ev.get("transcript", 0)),
                },
                "samples": samples[tid],
                "children": [],
            }
        )
    catalog.sort(key=lambda x: x["count"], reverse=True)
    flat = [{k: v for k, v in p.items() if k != "children"} for p in catalog]

    meta = {
        "totalEpisodes": len(episodes),
        "episodesWithTheme": sum(1 for t in tagged if t),
        "parentCount": len(catalog),
        "placeParentCount": sum(1 for t in catalog if t["kind"] in ("local", "story")),
        "topicParentCount": sum(1 for t in catalog if t["kind"] in ("frame", "domain")),
        "childCount": 0,
        "themeCount": len(catalog),
        "evidenceSourceCounts": dict(src_counts),
        "episodesWithTranscriptEvidence": int(src_counts.get("transcript", 0) + src_counts.get("stt", 0) + src_counts.get("youtube", 0)),
        "episodesWithNotesEvidence": int(src_counts.get("notes", 0) + src_counts.get("show-notes", 0)),
        "episodesWithTitleOnlyEvidence": int(src_counts.get("title", 0)),
        "method": "flat-transcript-first-show-priors",
        "note": (
            "Flat themes. Per-episode evidence priority: transcript → notes → "
            "title/show. Geo + actors from title/show; show priors baseline known "
            "coverage. Noisy domains need multiple hits in long transcripts."
        ),
    }
    return tagged, {"meta": meta, "themes": catalog, "flat": flat}


def main() -> None:
    episodes = json.loads((TABLES / "episodes.json").read_text(encoding="utf-8"))
    notes_path = TABLES / "notes.json"
    notes = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.exists() else {}
    full_texts: dict[str, str] = {}
    try:
        from transcript_store import connect, full_text_map

        conn = connect()
        full_texts = full_text_map(conn)
        conn.close()
        print(f"full_transcripts_loaded={len(full_texts)}")
    except Exception as exc:  # noqa: BLE001
        print(f"full store unavailable ({exc}); using slim notes only")
    tagged, doc = tag_all(episodes, notes, full_texts)
    (TABLES / "episode-themes.json").write_text(
        json.dumps(tagged, separators=(",", ":")), encoding="utf-8"
    )
    (TABLES / "themes.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"themes={doc['meta']['themeCount']} "
        f"tagged={doc['meta']['episodesWithTheme']}/{doc['meta']['totalEpisodes']}"
    )
    for t in doc["themes"][:40]:
        print(f"  {t['count']:5d}  {t['name']}  [{t['kind']}]")
    print("  …")
    for t in doc["themes"][40:]:
        print(f"  {t['count']:5d}  {t['name']}  [{t['kind']}]")


if __name__ == "__main__":
    main()
