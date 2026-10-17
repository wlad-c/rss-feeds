#!/usr/bin/env python3
"""Rebuild themes.json + episode-themes.json as a flat single-level taxonomy.

Approved design:
  - One click per theme; no parent/child hierarchy.
  - Local themes are always specific (Brazilian elections, US government, …)
    never bare country names.
  - Region leftovers use named regions (Europe, Latin America, Asia-Pacific, …)
    not “other countries”.
  - China–Taiwan, Indo-Pacific, Israel–Gaza, Ukraine, Russia are separate.
  - Geo cues for local/story themes require title/show (not body alone).
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
        r"\blula\b", r"\bstf\b", r"\btse\b", r"\bplanalto\b", r"\bbras[ií]lia\b",
        r"\bmoraes\b", r"\bfl[aá]vio bolsonar", r"\bhaddad\b", r"\btarc[ií]sio\b",
        r"\bxand[aã]o\b", r"\bdatafolha\b", r"\bcongresso nacional\b",
        r"\bc[aâ]mara dos deputados\b", r"\bsenado federal\b",
    ],
    "au": [
        r"\baustralia\b", r"\baustralian\b", r"\balbanese\b", r"\balbo\b",
        r"\bdutton\b", r"\bcanberra\b", r"\bqueensland\b", r"\bnsw\b",
        r"\bvictoria\b", r"\bsydney\b", r"\bmelbourne\b", r"\bone nation\b",
        r"\bpauline hanson\b", r"\baustralian politics\b", r"\bpolitics now\b",
        r"\babc news\b", r"\brobodebt\b", r"\bnacc\b",
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
        r"\bfrench\b", r"\bmacron\b", r"\bgermany\b", r"\balemanha\b",
        r"\bgerman\b", r"\bscholz\b", r"\bmerkel\b", r"\buk\b", r"\bbritain\b",
        r"\bbritish\b", r"\bunited kingdom\b", r"\bbrexit\b", r"\bstarmer\b",
        r"\bspain\b", r"\bespanha\b", r"\bitaly\b", r"\bitalia\b", r"\bmeloni\b",
        r"\bnetherlands\b", r"\bsweden\b", r"\bpoland\b", r"\bpol[oô]nia\b",
        r"\bhungary\b", r"\bhungria\b", r"\borb[aá]n\b", r"\bportugal\b",
        r"\bbrussels\b", r"\bafd\b",
    ],
    "apac": [
        r"\bmalaysia\b", r"\bmalaysian\b", r"\bkuala lumpur\b", r"\banwar\b",
        r"\bmahathir\b", r"\bsingapore\b", r"\bindonesia\b", r"\bjakarta\b",
        r"\bthailand\b", r"\bvietnam\b", r"\bphilippines\b", r"\basean\b",
        r"\bsoutheast asia\b", r"\bsouth[- ]east asia\b", r"\basia[- ]pacific\b",
        r"\bjapan\b", r"\bjapanese\b", r"\btokyo\b", r"\bkorea\b", r"\bkorean\b",
        r"\bseoul\b", r"\bindia\b", r"\bindian\b", r"\bmodi\b", r"\bpakistan\b",
        r"\bbangladesh\b",
    ],
    "cn_tw": [
        r"\bchina\b", r"\bchinese\b", r"\bbeijing\b", r"\bxi jinping\b",
        r"\btaiwan\b", r"\btaipei\b", r"\bhong kong\b", r"\bpla\b",
        r"\bchinese communist\b",
    ],
    "indopac": [
        r"\bindo[- ]pacific\b", r"\baukus\b", r"\bquad\b",
        r"\bsouth china sea\b", r"\bpacific deterrence\b",
        r"\bfreedom of navigation\b",
    ],
    "israel_gaza": [
        r"\bisrael\b", r"\bisraeli\b", r"\bgaza\b", r"\bpalestinian\b",
        r"\bpalestina\b", r"\bhamas\b", r"\bnetanyahu\b", r"\bwest bank\b",
        r"\bidf\b", r"\bhezbollah\b", r"\blebanon\b",
    ],
    "me_other": [
        r"\biran\b", r"\btehran\b", r"\bsaudi\b", r"\bmiddle east\b",
        r"\bqatar\b", r"\bsyria\b", r"\byemen\b", r"\bhouthis\b",
        r"\biraq\b", r"\bbaghdad\b",
    ],
    "ukraine": [
        r"\bukraine\b", r"\bukrainian\b", r"\bzelensky\b", r"\bkyiv\b",
        r"\bkiev\b", r"\bdonbas\b", r"\bcrimea\b", r"\bmariupol\b",
    ],
    "russia": [
        r"\brussia\b", r"\brussian\b", r"\bputin\b", r"\bmoscow\b",
        r"\bkremlin\b", r"\blavrov\b",
    ],
    "latam": [
        r"\bargentina\b", r"\bchile\b", r"\bcolombia\b", r"\bvenezuela\b",
        r"\bmexico\b", r"\bm[eé]xico\b", r"\bperu\b", r"\bbolivia\b",
        r"\becuador\b", r"\buruguay\b", r"\bparaguay\b", r"\bcuba\b",
        r"\bnicaragua\b", r"\bmaduro\b", r"\bmilei\b", r"\bboric\b",
        r"\bpetro\b", r"\bamlo\b", r"\blatin america\b", r"\bam[eé]rica latina\b",
    ],
    "af": [
        r"\bafrica\b", r"\bafrican\b", r"\bnigeria\b", r"\bkenya\b",
        r"\bsouth africa\b", r"\bethiopia\b", r"\bsahel\b", r"\bsudan\b",
        r"\begypt\b", r"\bmorocco\b", r"\bghana\b", r"\brwanda\b",
    ],
}

# ---------------------------------------------------------------------------
# Topic patterns (content)
# ---------------------------------------------------------------------------
ELEC = [
    r"\beleições\b", r"\beleição\b", r"\beleic[oõ]es\b", r"\beleic[aã]o\b",
    r"\belection\b", r"\belectoral\b", r"\bvoto\b", r"\bvota[cç]",
    r"\bvoting\b", r"\bballot\b", r"\burnas\b", r"\bcandidato\b",
    r"\bcandidate\b", r"\bcampanha\b", r"\bcampaign\b", r"\bprim[aá]rias\b",
    r"\bprimary\b", r"\brunoff\b", r"\bsegundo turno\b", r"\bpolls?\b",
    r"\bpesquisa eleitoral\b",
]
GOV = [
    r"\bgoverno\b", r"\bgovernment\b", r"\bminist[eé]rio\b", r"\bminister\b",
    r"\bcabinet\b", r"\bcongresso\b", r"\bparliament\b", r"\bsenado\b",
    r"\bsenate\b", r"\bc[aâ]mara\b", r"\bplanalto\b", r"\bexecutivo\b",
    r"\bcasa branca\b", r"\bwhite house\b", r"\blegislat",
]
COURT = [
    r"\bstf\b", r"\btse\b", r"\bstj\b", r"\bsupremo\b", r"\bsupreme court\b",
    r"\bscotus\b", r"\bjudici[aá]rio\b", r"\bjudiciary\b", r"\btribunal\b",
    r"\bcourt\b", r"\binqu[eé]rito\b", r"\bimpeachment\b", r"\brule of law\b",
    r"\bestado de direito\b", r"\bconstitui[cç]", r"\bconstitution\b",
]
MEDIA = [
    r"\bm[ií]dia\b", r"\bmedia\b", r"\bimprensa\b", r"\bpress\b",
    r"\bjornalismo\b", r"\bjournalis", r"\brede social\b", r"\bsocial media\b",
    r"\btwitter\b", r"\bfacebook\b", r"\bcensura\b", r"\bcensorship\b",
    r"\bdesinforma", r"\bdisinfo", r"\bfake news\b",
]
ECON = [
    r"\beconomia\b", r"\beconomy\b", r"\binfla[cç]", r"\binflation\b",
    r"\bjuros\b", r"\binterest rate\b", r"\bmercado\b", r"\bmarkets\b",
    r"\bgdp\b", r"\bpib\b", r"\bbolsa\b", r"\bstocks\b", r"\btarifa\b",
    r"\btariff\b", r"\bcom[eé]rcio\b", r"\btrade\b", r"\bdesemprego\b",
    r"\bunemployment\b", r"\bbanco central\b", r"\bfederal reserve\b",
    r"\brecess", r"\bor[cç]amento\b", r"\bbudget\b",
]
CRIME = [
    r"\bcrime\b", r"\bpol[ií]cia\b", r"\bpolice\b", r"\bhomic[ií]dio\b",
    r"\bmurder\b", r"\btr[aá]fico\b", r"\bcorrup[cç]", r"\bcorruption\b",
    r"\bpris[aã]o\b", r"\bprison\b", r"\btiroteio\b", r"\bviolence\b",
    r"\bviol[eê]ncia\b",
]
DEF = [
    r"\bguerra\b", r"\bwar\b", r"\bmilitary\b", r"\bmilitar\b",
    r"\bdefence\b", r"\bdefense\b", r"\bnato\b", r"\botan\b",
    r"\barma\b", r"\bweapon\b", r"\bmissile\b", r"\bairstrike\b",
    r"\bfor[cç]as armadas\b", r"\bpentagon\b", r"\bsoldiers?\b",
]
CLIM = [
    r"\bclima\b", r"\bclimate\b", r"\baquecimento global\b",
    r"\bglobal warming\b", r"\bcarbon\b", r"\bemiss[oõ]es\b", r"\bemissions\b",
    r"\bpetr[oó]leo\b", r"\boil\b", r"\bcarv[aã]o\b", r"\bcoal\b",
    r"\brenov[aá]vel\b", r"\brenewable\b", r"\benergia solar\b",
]
MIG = [
    r"\bimigra", r"\bmigra[cç]", r"\bmigration\b", r"\brefugiad",
    r"\brefugee\b", r"\basylum\b", r"\bfronteira\b", r"\bborder\b",
    r"\bdeport", r"\bvisto\b", r"\bvisa\b",
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

# Flat theme catalog. kind: local | story | frame | domain
# Local/story: require geo_key match on title_show (+ topic_pats on body when set).
THEMES: list[dict] = [
    # --- Brazil ---
    {"id": "br-elections", "name": "Brazilian elections", "kind": "local",
     "blurb": "Elections, campaigns, and voting in Brazil.",
     "geo": "br", "topic": ELEC},
    {"id": "br-government", "name": "Brazilian government", "kind": "local",
     "blurb": "Brazilian executive, ministries, and legislature.",
     "geo": "br", "topic": GOV},
    {"id": "br-courts", "name": "Brazilian courts", "kind": "local",
     "blurb": "STF, TSE, and Brazilian judicial politics.",
     "geo": "br", "topic": COURT},
    {"id": "br-media", "name": "Brazilian media", "kind": "local",
     "blurb": "Press, platforms, and media regulation in Brazil.",
     "geo": "br", "topic": MEDIA},
    {"id": "br-economy", "name": "Brazilian economy", "kind": "local",
     "blurb": "Brazilian markets, inflation, and fiscal politics.",
     "geo": "br", "topic": ECON},
    {"id": "br-crime", "name": "Brazilian crime & security", "kind": "local",
     "blurb": "Crime, policing, and security in Brazil.",
     "geo": "br", "topic": CRIME},
    # --- Australia ---
    {"id": "au-elections", "name": "Australian elections", "kind": "local",
     "blurb": "Federal and state elections in Australia.",
     "geo": "au", "topic": ELEC},
    {"id": "au-government", "name": "Australian government", "kind": "local",
     "blurb": "Australian government, parliament, and parties.",
     "geo": "au", "topic": GOV},
    {"id": "au-economy", "name": "Australian economy", "kind": "local",
     "blurb": "Australian economy, rates, and budgets.",
     "geo": "au", "topic": ECON},
    {"id": "au-climate", "name": "Australian climate & energy", "kind": "local",
     "blurb": "Climate and energy policy in Australia.",
     "geo": "au", "topic": CLIM},
    # --- United States ---
    {"id": "us-elections", "name": "US elections", "kind": "local",
     "blurb": "US elections, primaries, and campaigns.",
     "geo": "us", "topic": ELEC},
    {"id": "us-government", "name": "US government", "kind": "local",
     "blurb": "US White House, Congress, and federal government.",
     "geo": "us", "topic": GOV},
    {"id": "us-courts", "name": "US courts", "kind": "local",
     "blurb": "SCOTUS and US courts.",
     "geo": "us", "topic": COURT},
    {"id": "us-economy", "name": "US economy", "kind": "local",
     "blurb": "US economy, Fed, and markets.",
     "geo": "us", "topic": ECON},
    {"id": "us-immigration", "name": "US immigration", "kind": "local",
     "blurb": "US immigration, borders, and deportation.",
     "geo": "us", "topic": MIG},
    {"id": "us-foreign-policy", "name": "US foreign policy", "kind": "local",
     "blurb": "US foreign policy and diplomacy.",
     "geo": "us", "topic": DIPL},
    # --- Regional locals ---
    {"id": "eu-elections", "name": "European elections", "kind": "local",
     "blurb": "Elections across Europe and the EU.",
     "geo": "eu", "topic": ELEC},
    {"id": "eu-government", "name": "European government", "kind": "local",
     "blurb": "European governments and EU institutions.",
     "geo": "eu", "topic": GOV},
    {"id": "latam-elections", "name": "Latin American elections", "kind": "local",
     "blurb": "Elections in Latin America outside Brazil.",
     "geo": "latam", "topic": ELEC},
    {"id": "latam-government", "name": "Latin American government", "kind": "local",
     "blurb": "Governments across Latin America outside Brazil.",
     "geo": "latam", "topic": GOV},
    {"id": "apac-elections", "name": "Asia-Pacific elections", "kind": "local",
     "blurb": "Elections across Asia-Pacific (ex China/Taiwan, Australia, US).",
     "geo": "apac", "topic": ELEC},
    {"id": "apac-government", "name": "Asia-Pacific government", "kind": "local",
     "blurb": "Governments across Asia-Pacific (ex China/Taiwan, Australia, US).",
     "geo": "apac", "topic": GOV},
    {"id": "af-elections", "name": "African elections", "kind": "local",
     "blurb": "Elections across Africa.",
     "geo": "af", "topic": ELEC},
    {"id": "af-government", "name": "African government", "kind": "local",
     "blurb": "Governments across Africa.",
     "geo": "af", "topic": GOV},
    {"id": "cn-government", "name": "Chinese government", "kind": "local",
     "blurb": "Chinese Communist Party and state institutions.",
     "geo": "cn_tw", "topic": GOV},
    {"id": "me-government", "name": "Middle East government", "kind": "local",
     "blurb": "Governments and regimes across the Middle East (ex Israel–Gaza war tag).",
     "geo": "me_other", "topic": GOV},
    {"id": "ru-government", "name": "Russian government", "kind": "local",
     "blurb": "Russian government and Kremlin politics.",
     "geo": "russia", "topic": GOV},
    # --- Storylines (geo-gated; specific, not bare regions) ---
    {"id": "israel-gaza-war", "name": "Israel–Gaza war", "kind": "story",
     "blurb": "Israel–Gaza war and related coverage.",
     "geo": "israel_gaza", "topic": None},
    {"id": "ukraine-war", "name": "Ukraine war", "kind": "story",
     "blurb": "Russia’s war against Ukraine.",
     "geo": "ukraine", "topic": None},
    {"id": "china-taiwan", "name": "China–Taiwan tensions", "kind": "story",
     "blurb": "China–Taiwan tensions and cross-strait conflict risk.",
     "geo": "cn_tw", "topic": WAR + [r"\btaiwan\b", r"\btaipei\b", r"\bstrait\b"]},
    {"id": "indo-pacific-security", "name": "Indo-Pacific security", "kind": "story",
     "blurb": "AUKUS, Quad, and Indo-Pacific security architecture.",
     "geo": "indopac", "topic": None},
    # --- Frames ---
    {"id": "extreme-right", "name": "Extreme right", "kind": "frame",
     "blurb": "Far-right and extreme-right movements worldwide.",
     "geo": None, "topic": [
         r"\bextrema[- ]?direita\b", r"\bfar[- ]?right\b", r"\balt[- ]?right\b",
         r"\bdireita radical\b", r"\bneonazi\b", r"\bneo[- ]?nazi\b",
         r"\bfascis", r"\bwhite supremac", r"\bsupremacista\b",
     ]},
    {"id": "populism", "name": "Populism", "kind": "frame",
     "blurb": "Populist politics and messaging.",
     "geo": None, "topic": [r"\bpopulist\b", r"\bpopulismo\b", r"\bpopulism\b"]},
    {"id": "authoritarianism", "name": "Authoritarianism", "kind": "frame",
     "blurb": "Authoritarian rule, dictatorships, and illiberal politics.",
     "geo": None, "topic": [
         r"\bautoritar", r"\bauthoritarian\b", r"\bditadura\b",
         r"\bdictatorship\b", r"\bautocrat", r"\billiberal\b",
         r"\bgolpe\b", r"\bcoup\b",
     ]},
    {"id": "gender", "name": "Gender", "kind": "frame",
     "blurb": "Gender, feminism, abortion, and LGBTQ+ discussions.",
     "geo": None, "topic": [
         r"\bg[eê]nero\b", r"\bgender\b", r"\bfeminis", r"\bmachismo\b",
         r"\baborto\b", r"\babortion\b", r"\bmisogyn", r"\bwomen'?s rights\b",
         r"\bdireitos? das mulheres\b", r"\blgbt", r"\btransg[eê]nero\b",
         r"\btransgender\b",
     ]},
    {"id": "human-rights", "name": "Human rights", "kind": "frame",
     "blurb": "Human rights, torture, and civil liberties.",
     "geo": None, "topic": [
         r"\bdireitos? humanos?\b", r"\bhuman rights\b", r"\bamnesty\b",
         r"\btortura\b", r"\btorture\b", r"\bliberdade de express",
         r"\bfreedom of (speech|expression)\b",
     ]},
    {"id": "race-indigenous", "name": "Race & Indigenous", "kind": "frame",
     "blurb": "Race, racism, and Indigenous rights.",
     "geo": None, "topic": [
         r"\bracis", r"\bracial\b", r"\bnegro\b", r"\bblack lives\b",
         r"\bind[ií]gena\b", r"\bindigenous\b", r"\bquilombola\b",
         r"\bapartheid\b", r"\bcotas raciais\b",
     ]},
    # --- Domains ---
    {"id": "economy", "name": "Economy & markets", "kind": "domain",
     "blurb": "Economy, markets, inflation, and trade.",
     "geo": None, "topic": ECON},
    {"id": "defence-war", "name": "Defence & war", "kind": "domain",
     "blurb": "Military conflict, defence, and weapons.",
     "geo": None, "topic": DEF},
    {"id": "climate-energy", "name": "Climate & energy", "kind": "domain",
     "blurb": "Climate policy, fossils, and renewables.",
     "geo": None, "topic": CLIM},
    {"id": "ai-tech", "name": "AI & technology", "kind": "domain",
     "blurb": "Artificial intelligence, platforms, and tech industry.",
     "geo": None, "topic": [
         r"\bai\b", r"\bartificial intelligence\b",
         r"\bintelig[eê]ncia artificial\b", r"\bchatgpt\b", r"\bopenai\b",
         r"\bmachine learning\b", r"\balgoritmo\b", r"\balgorithm\b",
         r"\bbig tech\b", r"\bsilicon valley\b", r"\bsemiconductor\b",
     ]},
    {"id": "health-science", "name": "Health & science", "kind": "domain",
     "blurb": "Public health, pandemics, medicine, and science.",
     "geo": None, "topic": [
         r"\bsa[uú]de\b", r"\bhealth\b", r"\bcovid\b", r"\bpandemia\b",
         r"\bpandemic\b", r"\bvacina\b", r"\bvaccine\b", r"\bhospital\b",
         r"\bcient[ií]fic", r"\bscience\b",
     ]},
    {"id": "diplomacy", "name": "Diplomacy", "kind": "domain",
     "blurb": "Diplomacy, foreign policy, and multilateral forums.",
     "geo": None, "topic": DIPL},
    {"id": "migration", "name": "Migration & borders", "kind": "domain",
     "blurb": "Migration, asylum, and borders.",
     "geo": None, "topic": MIG},
    {"id": "crime", "name": "Crime & policing", "kind": "domain",
     "blurb": "Crime, policing, and corruption.",
     "geo": None, "topic": CRIME},
    {"id": "culture", "name": "Culture & entertainment", "kind": "domain",
     "blurb": "Film, TV, music, games, and arts.",
     "geo": None, "topic": [
         r"\bfilme\b", r"\bfilm\b", r"\bcinema\b", r"\bnetflix\b",
         r"\bm[uú]sica\b", r"\bmusic\b", r"\bvideogame\b", r"\bcelebridade\b",
         r"\boscar\b", r"\bs[eé]rie\b", r"\btv show\b", r"\bsongwriter\b",
     ]},
    {"id": "sport", "name": "Sport", "kind": "domain",
     "blurb": "Football, Olympics, and sport.",
     "geo": None, "topic": [
         r"\bfutebol\b", r"\bfootball\b", r"\bsoccer\b", r"\bcopa do mundo\b",
         r"\bworld cup\b", r"\bolimp[ií]", r"\bolympic", r"\bnba\b",
         r"\bnfl\b", r"\btennis\b", r"\bformula ?1\b",
     ]},
    {"id": "ideas", "name": "Ideas & society", "kind": "domain",
     "blurb": "Philosophy, psychology, and everyday society.",
     "geo": None, "topic": [
         r"\bfilosofia\b", r"\bphilosophy\b", r"\bpsicologia\b",
         r"\bpsychology\b", r"\bsociedade\b", r"\bsociety\b",
         r"\bcomportamento\b", r"\bbehaviour\b", r"\bbehavior\b",
         r"\b[eé]tica\b", r"\bethics\b", r"\brelacionamento\b",
         r"\brelationship\b", r"\bsa[uú]de mental\b", r"\bmental health\b",
     ]},
    {"id": "history", "name": "History", "kind": "domain",
     "blurb": "History, archives, and memory.",
     "geo": None, "topic": [
         r"\bhist[oó]ria\b", r"\bhistory\b", r"\barquiv", r"\barchive\b",
         r"\bguerra fria\b", r"\bcold war\b", r"\bimp[eé]rio\b",
         r"\bempire\b", r"\bcolonial\b", r"\bs[eé]culo\b",
     ]},
    {"id": "media", "name": "Media & information", "kind": "domain",
     "blurb": "Press, platforms, censorship, and disinformation.",
     "geo": None, "topic": MEDIA},
]


def _compile(pats: list[str] | None) -> list[re.Pattern]:
    if not pats:
        return []
    return [re.compile(p, re.I) for p in pats]


GEO_RE = {k: _compile(v) for k, v in GEO.items()}
COMPILED = [
    {
        **t,
        "geo_re": GEO_RE.get(t["geo"] or "", []),
        "topic_re": _compile(t.get("topic")),
    }
    for t in THEMES
]


def matches(pats: list[re.Pattern], text: str) -> bool:
    return bool(pats) and any(p.search(text) for p in pats)


def body_for_episode(i: int, notes: dict, full_texts: dict[str, str]) -> tuple[str, str]:
    if str(i) in full_texts and full_texts[str(i)]:
        note = notes.get(str(i)) or {}
        src = note.get("src") or "transcript"
        return full_texts[str(i)], src
    note = notes.get(str(i)) or {}
    return note.get("text") or "", note.get("src") or ""


def record_evidence(
    evidence: dict[str, Counter],
    tid: str,
    *,
    body: str,
    src: str,
    title_show: str,
    topic_re: list[re.Pattern],
    geo_re: list[re.Pattern],
) -> None:
    pats = topic_re or geo_re
    if body and pats and matches(pats, body):
        if src in ("transcript", "stt", "youtube"):
            evidence[tid]["transcript"] += 1
        else:
            evidence[tid]["notes"] += 1
    elif matches(pats or geo_re, title_show):
        evidence[tid]["title"] += 1


def tag_episode(
    *,
    title_show: str,
    hay: str,
    geo_hit: dict[str, bool],
) -> list[str]:
    """Return flat theme ids for one episode."""
    hits: list[str] = []

    def add(tid: str) -> None:
        if tid not in hits:
            hits.append(tid)

    # Country / region locals
    for t in COMPILED:
        if t["kind"] not in ("local", "story"):
            continue
        gk = t["geo"]
        if not gk or not geo_hit.get(gk):
            continue
        # Asia-Pacific must not swallow China/Taiwan, Australia, or US
        if gk == "apac" and (geo_hit.get("cn_tw") or geo_hit.get("au") or geo_hit.get("us")):
            continue
        # Europe compounds: skip if US cue dominates the same title (rare dual)
        if gk == "eu" and geo_hit.get("us") and t["id"].startswith("eu-"):
            # still allow if Europe is clearly present — keep
            pass
        topic_re = t["topic_re"]
        if t["kind"] == "story" and not topic_re:
            add(t["id"])
            continue
        if topic_re and matches(topic_re, hay):
            add(t["id"])

    # Frames + domains (content only)
    for t in COMPILED:
        if t["kind"] not in ("frame", "domain"):
            continue
        if matches(t["topic_re"], hay):
            add(t["id"])

    return hits


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

    for i, ep in enumerate(episodes):
        title = ep.get("e") or ""
        show = ep.get("p") or ""
        folder = (ep.get("f") or "").strip()
        body, src = body_for_episode(i, notes, full_texts)
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
        hay = f"{title_show}\n{body}"
        geo_hit = {k: matches(rs, title_show) for k, rs in GEO_RE.items()}

        hits = tag_episode(title_show=title_show, hay=hay, geo_hit=geo_hit)

        for tid in hits:
            t = theme_by_id[tid]
            counts[tid] += 1
            by_year[tid][str(ep.get("y") or "")] += 1
            record_evidence(
                evidence,
                tid,
                body=body,
                src=src,
                title_show=title_show,
                topic_re=t["topic_re"],
                geo_re=t["geo_re"],
            )
            if len(samples[tid]) < 8:
                samples[tid].append(
                    {"i": i, "e": title, "p": ep.get("p"), "d": ep.get("d")}
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
                "facet": t["kind"],  # UI compat: was place|topic
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

    tx_eps = sum(
        1
        for i in range(len(episodes))
        if (notes.get(str(i)) or {}).get("src") in ("transcript", "stt", "youtube")
    )
    meta = {
        "totalEpisodes": len(episodes),
        "episodesWithTheme": sum(1 for t in tagged if t),
        "parentCount": len(catalog),
        "placeParentCount": sum(1 for t in catalog if t["kind"] in ("local", "story")),
        "topicParentCount": sum(1 for t in catalog if t["kind"] in ("frame", "domain")),
        "childCount": 0,
        "themeCount": len(catalog),
        "episodesWithBodyText": sum(
            1
            for i in range(len(episodes))
            if body_for_episode(i, notes, full_texts)[0]
        ),
        "episodesWithTranscriptEvidence": int(tx_eps),
        "method": "flat-specific-local-taxonomy",
        "note": (
            "Single-level themes. Local labels are place×topic compounds "
            "(geo cue in title/show required). No bare country themes. "
            "China–Taiwan, Indo-Pacific, Israel–Gaza, Ukraine, and Russia "
            "are separate. Frames and domains are global content tags."
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
        f"themes={doc['meta']['themeCount']} children={doc['meta']['childCount']} "
        f"tagged={doc['meta']['episodesWithTheme']}/{doc['meta']['totalEpisodes']}"
    )
    for t in doc["themes"]:
        print(f"  {t['count']:5d}  {t['name']}  [{t['kind']}]")


if __name__ == "__main__":
    main()
