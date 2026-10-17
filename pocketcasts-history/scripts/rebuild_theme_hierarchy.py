#!/usr/bin/env python3
"""Rebuild themes.json + episode-themes.json with orthogonal place × topic facets.

Design (confirmed):
  1A — Place parents and topic parents are separate. Episodes can carry both.
  2  — Place facets for major regions/countries in the listening library.
  3B — Ambiguous language-global keywords (e.g. eleições, election, congresso)
       attach to the *topic* facet only. A *place* tag is added only when a
       clear geo cue also appears (title / show / safe folder / body).

Place children are actors & institutions of that place (Lula, Bolsonaro, Trump),
never generic topics like “elections”.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "tables"

# ---------------------------------------------------------------------------
# PLACE FACET — geo-gated. Parent fires only when geo patterns match.
# ---------------------------------------------------------------------------
PLACE_PARENTS: list[dict] = [
    {
        "id": "place-us",
        "name": "United States",
        "facet": "place",
        "blurb": "US domestic politics, institutions, and actors.",
        "patterns": [
            r"\bunited states\b", r"\bu\.s\.a\.\b", r"\bu\.s\.\b",
            r"\bamerican\b", r"\bwashington\b", r"\bwhite house\b",
            r"\btrump\b", r"\bbiden\b", r"\bkamala\b", r"\bharris\b", r"\bobama\b",
            r"\bmaga\b", r"\bscotus\b", r"\bsupreme court\b", r"\bcapitol\b",
            r"\bcapit[oó]lio\b", r"\bfbi\b", r"\bpentagon\b",
            r"\bhegseth\b", r"\bvance\b", r"\bmamdani\b",
        ],
        "children": [
            {
                "id": "us-trump-maga",
                "name": "Trump & MAGA",
                "blurb": "Trump, MAGA politics, and allied figures.",
                "patterns": [r"\btrump\b", r"\bmaga\b", r"\bhegseth\b", r"\bvance\b", r"\btucker carlson\b"],
            },
            {
                "id": "us-democrats-left",
                "name": "Democrats & the left",
                "blurb": "Biden, Harris, Democrats, and progressive US politics.",
                "patterns": [r"\bbiden\b", r"\bharris\b", r"\bkamala\b", r"\bdemocrat", r"\bmamdani\b", r"\bobama\b"],
            },
            {
                "id": "us-institutions",
                "name": "Congress, courts & agencies",
                "blurb": "US Congress, SCOTUS, FBI, and federal agencies.",
                "patterns": [
                    r"\bcongress\b", r"\bsenate\b", r"\bscotus\b", r"\bsupreme court\b",
                    r"\bfbi\b", r"\bpentagon\b", r"\bwhite house\b", r"\bimpeach",
                ],
            },
            {
                "id": "us-immigration-ice",
                "name": "ICE & US borders",
                "blurb": "US immigration enforcement and ICE.",
                "patterns": [r"\bice\b", r"\bdeport", r"\bborder patrol\b"],
            },
        ],
    },
    {
        "id": "place-brazil",
        "name": "Brazil",
        "facet": "place",
        "blurb": "Brazilian politics, institutions, and actors.",
        "patterns": [
            r"\bbrasil\b", r"\bbrazil\b", r"\bbrasileir", r"\blula\b",
            r"\bbolsonar", r"\bplanalto\b", r"\btse\b", r"\bstf\b",
            r"\bdatafolha\b", r"\bmoraes\b", r"\bxand[aã]o\b",
            r"\bantipetismo\b", r"\bpetismo\b", r"\bplanalto\b",
            r"\bpol[ií]tica externa brasileira\b", r"\bcongresso nacional\b",
            r"\bc[aâ]mara dos deputados\b", r"\bsenado federal\b",
            r"\bs[aã]o paulo\b", r"\brio de janeiro\b", r"\bbras[ií]lia\b",
        ],
        "children": [
            {
                "id": "br-lula-pt",
                "name": "Lula & PT",
                "blurb": "Lula, PT, and allied Brazilian campaign messaging.",
                "patterns": [r"\blula\b", r"\bantipetismo\b", r"\bpetismo\b", r"(?<![a-z])pt(?![a-z])"],
            },
            {
                "id": "br-bolsonaro",
                "name": "Bolsonaro family",
                "blurb": "Bolsonaro, Flávio, and bolsonarista politics.",
                "patterns": [r"\bbolsonar", r"\bfl[aá]vio bolsonar", r"\bantibolsonar"],
            },
            {
                "id": "br-courts-tse-stf",
                "name": "TSE, STF & Brazilian courts",
                "blurb": "Electoral court, Supremo, and Brazilian judicial politics.",
                "patterns": [r"\btse\b", r"\bstf\b", r"\bmoraes\b", r"\bxand[aã]o\b"],
            },
            {
                "id": "br-congress",
                "name": "Congresso & Orçamento",
                "blurb": "Brazilian legislature and budget politics.",
                "patterns": [
                    r"\bcongresso nacional\b", r"\bc[aâ]mara dos deputados\b",
                    r"\bsenado federal\b", r"\bor[cç]amento\b",
                ],
            },
        ],
    },
    {
        "id": "place-australia",
        "name": "Australia",
        "facet": "place",
        "blurb": "Australian politics, parties, and institutions.",
        "patterns": [
            r"\baustralia\b", r"\baustralian\b", r"\bcanberra\b",
            r"\balbanese\b", r"\balbo\b", r"\bdutton\b", r"\bone nation\b",
            r"\bparliament house\b", r"\bnacc\b", r"\brobodebt\b",
            r"\brba\b", r"\babc news\b", r"\bpolitics now\b",
            r"\baustralian politics\b",
        ],
        "children": [
            {
                "id": "au-labor-albo",
                "name": "Labor & Albanese",
                "blurb": "Labor government and Albanese's agenda.",
                "patterns": [r"\balbanese\b", r"\balbo\b", r"\blabor\b", r"\blabour\b"],
            },
            {
                "id": "au-coalition-right",
                "name": "Coalition & right",
                "blurb": "Coalition, Liberals, Nationals, One Nation, Dutton.",
                "patterns": [r"\bcoalition\b", r"\bdutton\b", r"\bone nation\b", r"\bliberals?\b", r"\bnationals?\b"],
            },
            {
                "id": "au-greens",
                "name": "Greens & crossbench",
                "blurb": "Greens strategy and crossbench politics.",
                "patterns": [r"\bgreens\b", r"\bcrossbench\b"],
            },
            {
                "id": "au-accountability",
                "name": "Robodebt & integrity",
                "blurb": "Robodebt, NACC, and integrity stories.",
                "patterns": [r"\brobodebt\b", r"\bnacc\b", r"\bintegrity commission\b"],
            },
        ],
    },
    {
        "id": "place-europe",
        "name": "Europe",
        "facet": "place",
        "blurb": "European governments, EU politics, and continental crises.",
        "patterns": [
            r"\beurope\b", r"\beuropean\b", r"\beuropean union\b", r"\beu parliament\b",
            r"\bfran[cç]a\b", r"\bfrance\b", r"\bgermany\b", r"\balemanha\b",
            r"\bbritain\b", r"\bbrexit\b", r"\bunited kingdom\b", r"\bmacron\b",
            r"\bscholz\b", r"\bstarmer\b", r"\bafd\b", r"\bitalia\b", r"\bitaly\b",
            r"\bspain\b", r"\bespanha\b", r"\bceuta\b", r"\bhungria\b", r"\bhungary\b",
            r"\bpol[oô]nia\b", r"\bpoland\b", r"\bnepal\b",  # keep nepal out - mistake
        ],
        "children": [
            {
                "id": "eu-western",
                "name": "Western Europe",
                "blurb": "France, Germany, UK, Italy, Spain, and neighbours.",
                "patterns": [
                    r"\bfran[cç]a\b", r"\bfrance\b", r"\bgermany\b", r"\balemanha\b",
                    r"\bbritain\b", r"\bbrexit\b", r"\bmacron\b", r"\bscholz\b",
                    r"\bstarmer\b", r"\bitalia\b", r"\bitaly\b", r"\bspain\b",
                    r"\bespanha\b", r"\bunited kingdom\b", r"\bceuta\b",
                ],
            },
            {
                "id": "eu-institutions-farright",
                "name": "EU & far right",
                "blurb": "European Union politics and far-right parties.",
                "patterns": [
                    r"\beuropean union\b", r"\beu parliament\b", r"\bafd\b",
                    r"\bfar.?right\b", r"\bextrema-?direita\b", r"\bhungria\b", r"\bhungary\b",
                ],
            },
        ],
    },
    {
        "id": "place-china-indo-pacific",
        "name": "China & Indo-Pacific",
        "facet": "place",
        "blurb": "China, Taiwan, ASEAN, AUKUS, and regional security.",
        "patterns": [
            r"\bchina\b", r"\bchinese\b", r"\bbeijing\b", r"\bxi jinping\b",
            r"\btaiwan\b", r"\baukus\b", r"\bquad\b", r"\basean\b",
            r"\bsingapore\b", r"\bindo-?pacific\b", r"\bnorth korea\b",
            r"\bmalaysia\b", r"\bphilippines\b", r"\bvietnam\b", r"\bjapan\b",
        ],
        "children": [
            {
                "id": "cip-china-beijing",
                "name": "China & Beijing",
                "blurb": "China domestic politics and Beijing's foreign policy.",
                "patterns": [r"\bchina\b", r"\bchinese\b", r"\bbeijing\b", r"\bxi jinping\b"],
            },
            {
                "id": "cip-taiwan",
                "name": "Taiwan",
                "blurb": "Taiwan Strait and cross-strait tensions.",
                "patterns": [r"\btaiwan\b"],
            },
            {
                "id": "cip-aukus-alliances",
                "name": "AUKUS & alliances",
                "blurb": "AUKUS, Quad, and Indo-Pacific alliance politics.",
                "patterns": [r"\baukus\b", r"\bquad\b"],
            },
            {
                "id": "cip-asean-sea",
                "name": "ASEAN & Southeast Asia",
                "blurb": "ASEAN states and Southeast Asian geopolitics.",
                "patterns": [
                    r"\basean\b", r"\bsingapore\b", r"\bmalaysia\b",
                    r"\bindonesia\b", r"\bphilippines\b", r"\bvietnam\b",
                ],
            },
            {
                "id": "cip-korea-japan",
                "name": "Korea & Japan",
                "blurb": "Korean peninsula and Japan security issues.",
                "patterns": [r"\bnorth korea\b", r"\bsouth korea\b", r"\bkorea\b", r"\bjapan\b", r"\bkim jong\b"],
            },
        ],
    },
    {
        "id": "place-middle-east",
        "name": "Middle East",
        "facet": "place",
        "blurb": "Israel, Gaza, Iran, Gulf states, and regional diplomacy.",
        "patterns": [
            r"\bisrael\b", r"\bisraeli\b", r"\bgaza\b", r"\bhamas\b", r"\bhezbollah\b",
            r"\biran\b", r"\biranian\b", r"\btehran\b", r"\bsaudi\b", r"\bhouthi",
            r"\bnetanyahu\b", r"\bpalestin", r"\bir[aã]n\b", r"\blebanon\b",
            r"\byemen\b", r"\bqatar\b", r"\boccupied palestine\b",
        ],
        "children": [
            {
                "id": "me-israel-gaza",
                "name": "Israel–Gaza",
                "blurb": "Israel, Gaza, Hamas, and the war's aftermath.",
                "patterns": [r"\bgaza\b", r"\bhamas\b", r"\bisrael", r"\bnetanyahu\b", r"\boctober 7\b", r"\bpalestin"],
            },
            {
                "id": "me-iran",
                "name": "Iran & Tehran",
                "blurb": "Iran, nuclear stakes, and Tehran's regional role.",
                "patterns": [r"\biran\b", r"\biranian\b", r"\btehran\b", r"\bir[aã]n\b"],
            },
            {
                "id": "me-gulf-saudi",
                "name": "Gulf & Saudi Arabia",
                "blurb": "Saudi Arabia, Gulf states, and related flashpoints.",
                "patterns": [r"\bsaudi\b", r"\bqatar\b", r"\bu\.?a\.?e\.?\b", r"\bhouthi", r"\byemen\b"],
            },
            {
                "id": "me-lebanon-hezbollah",
                "name": "Lebanon & Hezbollah",
                "blurb": "Lebanon, Hezbollah, and northern-front dynamics.",
                "patterns": [r"\blebanon\b", r"\bhezbollah\b"],
            },
        ],
    },
    {
        "id": "place-ukraine-russia",
        "name": "Ukraine & Russia",
        "facet": "place",
        "blurb": "War, diplomacy, and Moscow–Kyiv dynamics.",
        "patterns": [
            r"\bukraine\b", r"\bukrainian\b", r"\brussia\b", r"\brussian\b",
            r"\bputin\b", r"\bzelensky", r"\bkyiv\b", r"\bkremlin\b", r"\bmoscow\b",
            r"\búcr[aá]nia\b", r"\br[uú]ssia\b",
        ],
        "children": [
            {
                "id": "ua-war-fighting",
                "name": "War & battlefield",
                "blurb": "Fighting, drones, offensives, and military developments.",
                "patterns": [r"\bdrone\b", r"\boffensive\b", r"\bbattle", r"\bmissile\b", r"\brefiner"],
            },
            {
                "id": "ua-putin-moscow",
                "name": "Putin & Moscow",
                "blurb": "Putin, Kremlin, and Russian strategy.",
                "patterns": [r"\bputin\b", r"\bkremlin\b", r"\bmoscow\b"],
            },
            {
                "id": "ua-zelensky-kyiv",
                "name": "Zelenskyy & Kyiv",
                "blurb": "Zelenskyy, Ukrainian politics, and Kyiv's position.",
                "patterns": [r"\bzelensky", r"\bkyiv\b"],
            },
            {
                "id": "ua-nato-west",
                "name": "NATO & Western support",
                "blurb": "NATO, sanctions, and Western military aid.",
                "patterns": [r"\bnato\b", r"\bsanction"],
            },
        ],
    },
    {
        "id": "place-latin-america",
        "name": "Latin America & Caribbean",
        "facet": "place",
        "blurb": "Venezuela, Mexico, Argentina, Colombia, and the region beyond Brazil.",
        "patterns": [
            r"\bvenezuela\b", r"\bmaduro\b", r"\bm[eé]xico\b", r"\bmexico\b",
            r"\bargentina\b", r"\bcol[oô]mbia\b", r"\bchile\b", r"\bper[uú]\b",
            r"\bcuba\b", r"\bhaiti\b", r"\blatin america\b", r"\bam[eé]rica latina\b",
            r"\bbukele\b", r"\bel salvador\b", r"\bbol[ií]via\b", r"\bhonduras\b",
            r"\bam[eé]rica latina\b",
        ],
        "children": [
            {
                "id": "latam-venezuela",
                "name": "Venezuela",
                "blurb": "Venezuela, Maduro, and related crises.",
                "patterns": [r"\bvenezuela\b", r"\bmaduro\b"],
            },
            {
                "id": "latam-southern-cone",
                "name": "Southern Cone & Andes",
                "blurb": "Argentina, Chile, Peru, Colombia, Bolivia.",
                "patterns": [r"\bargentina\b", r"\bchile\b", r"\bper[uú]\b", r"\bcol[oô]mbia\b", r"\bbol[ií]via\b"],
            },
            {
                "id": "latam-mexico-central",
                "name": "Mexico & Central America",
                "blurb": "Mexico, El Salvador, Honduras, and Central America.",
                "patterns": [
                    r"\bm[eé]xico\b", r"\bmexico\b", r"\bbukele\b", r"\bel salvador\b",
                    r"\bcuba\b", r"\bhaiti\b", r"\bhonduras\b",
                ],
            },
        ],
    },
    {
        "id": "place-africa",
        "name": "Africa",
        "facet": "place",
        "blurb": "African politics, conflict, and regional diplomacy.",
        "patterns": [
            r"\bafrica\b", r"\bafrican\b", r"\bnigeria\b", r"\bsouth africa\b",
            r"\bethiopia\b", r"\bsudan\b", r"\bsahel\b", r"\bmali\b",
            r"\bniger\b", r"\brwanda\b", r"\bcongo\b", r"\bkeny",
        ],
        "children": [
            {
                "id": "af-west-sahel",
                "name": "West Africa & Sahel",
                "blurb": "Sahel, coups, and West African politics.",
                "patterns": [r"\bsahel\b", r"\bmali\b", r"\bniger\b", r"\bnigeria\b"],
            },
            {
                "id": "af-broader",
                "name": "Southern & East Africa",
                "blurb": "South Africa, Horn of Africa, and East Africa.",
                "patterns": [r"\bsouth africa\b", r"\bethiopia\b", r"\bsudan\b", r"\brwanda\b", r"\bcongo\b", r"\bkeny"],
            },
        ],
    },
    {
        "id": "place-south-asia",
        "name": "India & South Asia",
        "facet": "place",
        "blurb": "India, Pakistan, Bangladesh, and South Asian politics.",
        "patterns": [
            r"\bindia\b", r"\bindian\b", r"\bmodi\b", r"\bpakistan\b",
            r"\bbangladesh\b", r"\bsri lanka\b", r"\bsouth asia\b", r"\bnepal\b",
            r"\barm[eê]nia\b", r"\barmenia\b",  # keep armenia under... actually Caucasus - skip
        ],
        "children": [
            {
                "id": "sa-india",
                "name": "India",
                "blurb": "Indian politics, Modi, and domestic debates.",
                "patterns": [r"\bindia\b", r"\bindian\b", r"\bmodi\b"],
            },
            {
                "id": "sa-neighbours",
                "name": "Pakistan & neighbours",
                "blurb": "Pakistan, Bangladesh, Sri Lanka, Nepal.",
                "patterns": [r"\bpakistan\b", r"\bbangladesh\b", r"\bsri lanka\b", r"\bnepal\b"],
            },
        ],
    },
]

# Fix accidental nepal in Europe patterns - remove it
for _p in PLACE_PARENTS:
    if _p["id"] == "place-europe":
        _p["patterns"] = [p for p in _p["patterns"] if "nepal" not in p]
    if _p["id"] == "place-south-asia":
        _p["patterns"] = [p for p in _p["patterns"] if "arm" not in p.lower() or "armenia" in p or "armênia" in p or "arménia" in p]
        # remove armenia from south asia - wrong region
        _p["patterns"] = [p for p in _p["patterns"] if "armen" not in p.lower() and "armên" not in p.lower()]

# ---------------------------------------------------------------------------
# TOPIC FACET — content themes. Ambiguous keywords live HERE, not under place.
# ---------------------------------------------------------------------------
TOPIC_PARENTS: list[dict] = [
    {
        "id": "topic-elections",
        "name": "Elections & democracy",
        "facet": "topic",
        "blurb": "Elections, polls, campaigns, and democratic contests — any country.",
        "patterns": [
            r"\belection", r"\bmidterm", r"\belei[cç]", r"\bpoll\b", r"\bcampaign",
            r"\bblue wave\b", r"\bturno\b", r"\bvoto\b", r"\bvoting\b", r"\bvotes?\b",
            r"\bballot\b", r"\bprimar(y|ies)\b", r"\breferend", r"\bplebiscito\b",
            r"\bdemocrac",
        ],
        "children": [
            {
                "id": "elec-polls-campaigns",
                "name": "Polls & campaigns",
                "blurb": "Horse-race coverage, polls, and campaign strategy.",
                "patterns": [r"\bpoll\b", r"\bcampaign", r"\bdatafolha\b", r"\bblue wave\b", r"\bturno\b"],
            },
            {
                "id": "elec-voting-rights",
                "name": "Voting & ballots",
                "blurb": "Voting mechanics, ballots, and electoral participation.",
                "patterns": [r"\bvoto\b", r"\bvoting\b", r"\bvotes?\b", r"\bballot\b", r"\babsten"],
            },
            {
                "id": "elec-contests",
                "name": "Election contests",
                "blurb": "Named elections, midterms, and runoff contests.",
                "patterns": [r"\belection", r"\bmidterm", r"\belei[cç]", r"\bprimar(y|ies)\b", r"\breferend"],
            },
        ],
    },
    {
        "id": "topic-institutions",
        "name": "Institutions & governance",
        "facet": "topic",
        "blurb": "Legislatures, courts, budgets, and state power — not tied to one country.",
        "patterns": [
            r"\bcongresso\b", r"\bparliament\b", r"\blegislat", r"\bjudici",
            r"\bgovernment\b", r"\bgoverno\b", r"\bbudget\b", r"\bor[cç]amento\b",
            r"\bfiscal\b", r"\bimpeach", r"\bcabinet\b",
        ],
        "children": [
            {
                "id": "inst-legislature",
                "name": "Legislatures",
                "blurb": "Parliaments, congresses, and law-making.",
                "patterns": [r"\bcongresso\b", r"\bparliament\b", r"\blegislat", r"\bc[aâ]mara\b", r"\bsenado\b"],
            },
            {
                "id": "inst-courts",
                "name": "Courts & judiciary",
                "blurb": "Courts and judicial power as governance.",
                "patterns": [r"\bjudici", r"\bcourt\b", r"\btribunal\b"],
            },
            {
                "id": "inst-budget",
                "name": "Budgets & fiscal policy",
                "blurb": "Budgets, spending, and fiscal politics.",
                "patterns": [r"\bbudget\b", r"\bfiscal\b", r"\bor[cç]amento\b", r"\bsubsidy\b"],
            },
        ],
    },
    {
        "id": "topic-economy",
        "name": "Economy & markets",
        "facet": "topic",
        "blurb": "Inflation, rates, trade, markets, housing, and business.",
        "patterns": [
            r"\beconomy\b", r"\beconomic\b", r"\binflation\b", r"\binfla[cç][aã]o\b",
            r"\binterest rate", r"\brecession\b", r"\btariff", r"\beconomia\b",
            r"\bmercado\b", r"\bhousing\b", r"\bmortgage\b", r"\bprivate equity\b",
            r"\bbanking\b", r"\bconsumer debt\b", r"\bbuy now.?pay later\b",
            r"\bsuperannuation\b", r"\bsuper fund\b",
        ],
        "children": [
            {
                "id": "econ-inflation-rates",
                "name": "Inflation & rates",
                "blurb": "Prices, central banks, and interest rates.",
                "patterns": [r"\binflation\b", r"\binfla[cç][aã]o\b", r"\binterest rate", r"\bjuro", r"\bfed\b", r"\brba\b"],
            },
            {
                "id": "econ-trade-tariffs",
                "name": "Trade & tariffs",
                "blurb": "Trade wars, tariffs, and supply chains.",
                "patterns": [r"\btariff", r"\btrade war\b", r"\btrade\b"],
            },
            {
                "id": "econ-markets-business",
                "name": "Markets & business",
                "blurb": "Markets, stocks, and corporate stories.",
                "patterns": [r"\bmarket", r"\bstock", r"\bip[eo]\b", r"\bmercado\b", r"\bprivate equity\b", r"\bbanking\b"],
            },
            {
                "id": "econ-housing-debt",
                "name": "Housing & household debt",
                "blurb": "Housing markets, mortgages, and consumer debt.",
                "patterns": [r"\bhousing\b", r"\bmortgage\b", r"\brent\b", r"\bconsumer debt\b", r"\bbuy now.?pay later\b"],
            },
        ],
    },
    {
        "id": "topic-defence",
        "name": "Defence & security",
        "facet": "topic",
        "blurb": "Military, intelligence, cyber, and strategic policy.",
        "patterns": [
            r"\bdefence\b", r"\bdefense\b", r"\bmilitary\b", r"\bnuclear\b",
            r"\bmissile\b", r"\bcyber\b", r"\bnational security\b", r"\bhack",
            r"\bnato\b",
        ],
        "children": [
            {
                "id": "def-military",
                "name": "Military & weapons",
                "blurb": "Armed forces, weapons, and force posture.",
                "patterns": [r"\bmilitary\b", r"\barmy\b", r"\bnavy\b", r"\bmissile\b", r"\bweapons?\b"],
            },
            {
                "id": "def-intel-cyber",
                "name": "Intelligence & cyber",
                "blurb": "Spy agencies, hacking, and cyber conflict.",
                "patterns": [r"\bintel", r"\bcia\b", r"\bcyber\b", r"\bhack"],
            },
            {
                "id": "def-nuclear",
                "name": "Nuclear",
                "blurb": "Nuclear weapons and deterrence.",
                "patterns": [r"\bnuclear\b"],
            },
        ],
    },
    {
        "id": "topic-climate",
        "name": "Climate & energy",
        "facet": "topic",
        "blurb": "Climate policy, renewables, fossils, and the energy transition.",
        "patterns": [
            r"\bclimate\b", r"\bemissions?\b", r"\brenewable", r"\bcoal\b",
            r"\belectric vehicle", r"\bclima\b", r"\benergia\b", r"\bcop\d*\b",
        ],
        "children": [
            {
                "id": "cl-climate-policy",
                "name": "Climate policy",
                "blurb": "Emissions targets, COP, and climate politics.",
                "patterns": [r"\bclimate\b", r"\bemissions?\b", r"\bnet.?zero\b", r"\bcop\d*\b", r"\bclima\b"],
            },
            {
                "id": "cl-fossil-fuels",
                "name": "Oil, gas & coal",
                "blurb": "Fossil fuels and extractive politics.",
                "patterns": [r"\bcoal\b", r"\boil\b", r"\bgas\b", r"\bpetr[oó]leo\b"],
            },
            {
                "id": "cl-renewables-ev",
                "name": "Renewables & EVs",
                "blurb": "Clean energy and electric vehicles.",
                "patterns": [r"\brenewable", r"\bsolar\b", r"\bwind\b", r"\bev\b", r"\belectric vehicle"],
            },
        ],
    },
    {
        "id": "topic-ai-tech",
        "name": "AI & technology",
        "facet": "topic",
        "blurb": "Artificial intelligence, platforms, and digital policy.",
        "patterns": [
            r"(?<![a-z])ai(?![a-z])", r"\bartificial intelligence\b", r"\bchatgpt\b",
            r"\bopenai\b", r"\btechnology\b", r"\bsocial media\b", r"\btiktok\b",
            r"\bintellig[eê]ncia artificial\b", r"\belon musk\b", r"\btesla\b",
            r"\bsemiconductor", r"\bchip\b", r"\bdata centre", r"\bdata center",
        ],
        "children": [
            {
                "id": "tech-ai",
                "name": "Artificial intelligence",
                "blurb": "AI models, labs, and AI policy.",
                "patterns": [
                    r"(?<![a-z])ai(?![a-z])", r"\bartificial intelligence\b",
                    r"\bchatgpt\b", r"\bopenai\b", r"\bintellig[eê]ncia artificial\b",
                ],
            },
            {
                "id": "tech-platforms",
                "name": "Platforms & social media",
                "blurb": "Big Tech platforms and social media politics.",
                "patterns": [
                    r"\bsocial media\b", r"\btiktok\b", r"\bgoogle\b", r"\balgorithm",
                    r"\bredes sociais\b", r"\bmeta\b", r"\bfacebook\b",
                ],
            },
            {
                "id": "tech-hardware-infra",
                "name": "Chips, cloud & hardware",
                "blurb": "Semiconductors, data centres, and tech infrastructure.",
                "patterns": [r"\bsemiconductor", r"\bchip\b", r"\bdata centre", r"\bdata center", r"\belon musk\b", r"\btesla\b"],
            },
        ],
    },
    {
        "id": "topic-health",
        "name": "Health & science",
        "facet": "topic",
        "blurb": "Public health, medicine, pandemics, and research.",
        "patterns": [
            r"\bcovid\b", r"\bcoronav[ií]rus\b", r"\bpandemic\b", r"\bpandemia\b",
            r"\bvaccine\b", r"\bhealth\b", r"\bcancer\b", r"\bdementia\b",
            r"\bscience\b", r"\bsa[uú]de\b", r"\bquarentena\b", r"\babortion\b",
            r"\babort[eo]\b",
        ],
        "children": [
            {
                "id": "health-pandemic",
                "name": "Pandemics & vaccines",
                "blurb": "Covid, pandemics, and vaccination.",
                "patterns": [
                    r"\bcovid\b", r"\bcoronav[ií]rus\b", r"\bpandemic\b", r"\bvaccine\b",
                    r"\bvacin", r"\bpandemia\b", r"\bquarentena\b",
                ],
            },
            {
                "id": "health-public",
                "name": "Public health & medicine",
                "blurb": "Hospitals, disease, and health systems.",
                "patterns": [
                    r"\bhealth\b", r"\bhospital\b", r"\bcancer\b", r"\bdementia\b",
                    r"\bsa[uú]de\b", r"\babortion\b", r"\babort[eo]\b",
                ],
            },
        ],
    },
    {
        "id": "topic-culture",
        "name": "Culture, film & entertainment",
        "facet": "topic",
        "blurb": "Movies, TV, books, music, games, and pop culture.",
        "patterns": [
            r"\bmovie\b", r"\bfilm\b", r"\bcinema\b", r"\bfilme\b", r"\bs[eé]ries?\b",
            r"\btv show\b", r"\bnetflix\b", r"\bhbo\b", r"\bgame of thrones\b",
            r"\bstranger things\b", r"\boscar\b", r"\bnerdcast\b", r"\bghibli",
            r"\banime\b", r"\bmusic\b", r"\bm[uú]sica\b", r"\bcinem[aá]tico\b",
            r"\bcultura pop\b", r"\bbook review\b", r"\blivro\b", r"\bjoker\b",
            r"\bcoringa\b", r"\brapaduracast\b", r"\bmilkshake chamado wanda\b",
            r"\bbraincast\b", r"\bentertaining\b",
        ],
        "children": [
            {
                "id": "cult-film-tv",
                "name": "Film & TV",
                "blurb": "Movies, series, streaming, and screen culture.",
                "patterns": [
                    r"\bmovie\b", r"\bfilm\b", r"\bcinema\b", r"\bfilme\b", r"\bs[eé]ries?\b",
                    r"\bnetflix\b", r"\bhbo\b", r"\bgame of thrones\b", r"\bstranger things\b",
                    r"\boscar\b", r"\bcinem[aá]tico\b", r"\bjoker\b", r"\bcoringa\b",
                    r"\bghibli", r"\banime\b", r"\brapaduracast\b",
                ],
            },
            {
                "id": "cult-music-games",
                "name": "Music, games & fandom",
                "blurb": "Music, games, comics, and fan culture.",
                "patterns": [
                    r"\bmusic\b", r"\bm[uú]sica\b", r"\bgaming\b", r"\bvideo ?game",
                    r"\bnerdcast\b", r"\bcultura pop\b", r"\bcomic\b", r"\bquadrinhos\b",
                    r"\bmilkshake chamado wanda\b",
                ],
            },
            {
                "id": "cult-books-arts",
                "name": "Books & arts",
                "blurb": "Books, theatre, and the arts.",
                "patterns": [r"\bbook review\b", r"\blivro\b", r"\bnovel\b", r"\btheatre\b", r"\btheater\b", r"\bexhibition\b"],
            },
        ],
    },
    {
        "id": "topic-sport",
        "name": "Sport",
        "facet": "topic",
        "blurb": "Football, Olympics, World Cup, and sporting culture.",
        "patterns": [
            r"\bsport\b", r"\besporte\b", r"\bfootball\b", r"\bsoccer\b",
            r"\bfutebol\b", r"\bcopa\b", r"\bworld cup\b", r"\bmundial\b",
            r"\bolympic", r"\bol[ií]mpiad", r"\bpremier league\b",
            r"\bnba\b", r"\bnfl\b", r"\btennis\b", r"\bcricket\b", r"\brugby\b",
            r"\bswans\b", r"\bafl\b",
        ],
        "children": [
            {
                "id": "sport-football",
                "name": "Football / soccer",
                "blurb": "Football clubs, leagues, and match culture.",
                "patterns": [r"\bfootball\b", r"\bsoccer\b", r"\bfutebol\b", r"\bpremier league\b", r"\bafl\b", r"\bswans\b"],
            },
            {
                "id": "sport-mega-events",
                "name": "World Cup & Olympics",
                "blurb": "World Cups, Olympics, and mega sporting events.",
                "patterns": [r"\bcopa\b", r"\bworld cup\b", r"\bmundial\b", r"\bolympic", r"\bol[ií]mpiad"],
            },
        ],
    },
    {
        "id": "topic-ideas",
        "name": "Ideas, mind & society",
        "facet": "topic",
        "blurb": "Philosophy, psychology, relationships, identity, and how we live.",
        "patterns": [
            r"\bphilosoph", r"\bfilosofi", r"\bpsycholog", r"\bpsicolog",
            r"\bmental health\b", r"\brelationship", r"\bidentit",
            r"\bethics?\b", r"\bmoral\b", r"\bhappiness\b", r"\bcognitiv",
            r"\bbehavio", r"\bbetter to know\b", r"\bhidden brain\b",
            r"\bmaking sense\b", r"\bsam harris\b", r"\bsociety\b", r"\bsociedade\b",
            r"\bideolog", r"\bobsess[aã]o chatgpt\b", r"\bgood to know\b",
        ],
        "children": [
            {
                "id": "ideas-philosophy",
                "name": "Philosophy & ethics",
                "blurb": "Moral questions, philosophy, and big ideas.",
                "patterns": [r"\bphilosoph", r"\bfilosofi", r"\bethics?\b", r"\bmoral\b", r"\bideolog", r"\bmarxism"],
            },
            {
                "id": "ideas-psychology",
                "name": "Psychology & behaviour",
                "blurb": "Mind, cognition, mental health, and behaviour.",
                "patterns": [
                    r"\bpsycholog", r"\bpsicolog", r"\bmental health\b", r"\bcognitiv",
                    r"\bbehavio", r"\bhidden brain\b", r"\bbetter to know\b",
                    r"\bobsess[aã]o chatgpt\b",
                ],
            },
            {
                "id": "ideas-relationships",
                "name": "Relationships & everyday life",
                "blurb": "Relationships, belonging, and how people live together.",
                "patterns": [r"\brelationship", r"\bfamily\b", r"\bfam[ií]lia\b", r"\bfriendship\b", r"\blove\b", r"\bmarriage\b"],
            },
        ],
    },
    {
        "id": "topic-history",
        "name": "History & memory",
        "facet": "topic",
        "blurb": "Historical episodes, archives, and how the past is told.",
        "patterns": [
            r"\bhistory\b", r"\bhist[oó]ria\b", r"\bhistorian\b", r"\bhistorical\b",
            r"\barchive\b", r"\bthroughline\b", r"\bhistory, geography & culture\b",
            r"\bsegunda guerra\b", r"\bworld war\b", r"\bfascis", r"\bnazis",
            r"\bcold war\b", r"\brevolução\b", r"\brevolution\b",
            r"\bempire\b", r"\bimp[eé]rio\b", r"\bcolonial",
        ],
        "children": [
            {
                "id": "hist-modern",
                "name": "Modern & 20th-century history",
                "blurb": "World wars, fascism, Cold War, and modern upheavals.",
                "patterns": [
                    r"\bsegunda guerra\b", r"\bworld war\b", r"\bfascis", r"\bnazis",
                    r"\bcold war\b", r"\brevolução\b", r"\brevolution\b",
                ],
            },
            {
                "id": "hist-empires-colonial",
                "name": "Empires & colonialism",
                "blurb": "Empire, colonialism, and decolonisation.",
                "patterns": [r"\bempire\b", r"\bimp[eé]rio\b", r"\bcolonial", r"\bdecolon"],
            },
            {
                "id": "hist-storytelling",
                "name": "Archives & storytelling",
                "blurb": "How history is researched, archived, and narrated.",
                "patterns": [r"\bhistory\b", r"\bhist[oó]ria\b", r"\bhistorian\b", r"\barchive\b", r"\bthroughline\b"],
            },
        ],
    },
    {
        "id": "topic-gender",
        "name": "Gender, race & identity",
        "facet": "topic",
        "blurb": "Gender, feminism, racism, LGBTQ+, and identity politics.",
        "patterns": [
            r"\bwomen\b", r"\bwoman\b", r"\bfeminist", r"\bfeminismo\b",
            r"\bmisogyn", r"\bgender\b", r"\blgbt", r"\bqueer\b", r"\btrans\b",
            r"\bracis", r"\bcoloris", r"\bfirst nations\b", r"\bindigenous\b",
            r"\bpatriarch", r"\bmulher", r"\bmachismo\b",
        ],
        "children": [
            {
                "id": "gid-gender-feminism",
                "name": "Gender & feminism",
                "blurb": "Women's rights, feminism, and gender politics.",
                "patterns": [
                    r"\bwomen\b", r"\bwoman\b", r"\bfeminist", r"\bfeminismo\b",
                    r"\bmisogyn", r"\bgender\b", r"\bmulher", r"\bpatriarch",
                ],
            },
            {
                "id": "gid-lgbtq",
                "name": "LGBTQ+",
                "blurb": "Queer, trans, and LGBTQ+ stories.",
                "patterns": [r"\blgbt", r"\bqueer\b", r"\btrans\b"],
            },
            {
                "id": "gid-race-indigenous",
                "name": "Race & Indigenous",
                "blurb": "Racism, colourism, and Indigenous politics.",
                "patterns": [r"\bracis", r"\bcoloris", r"\bfirst nations\b", r"\bindigenous\b"],
            },
        ],
    },
    {
        "id": "topic-media",
        "name": "Media & information",
        "facet": "topic",
        "blurb": "Press freedom, disinformation, and the information environment.",
        "patterns": [
            r"\bdisinfo", r"\bmisinfo", r"\bfake news\b", r"\bcensur",
            r"\bpress freedom\b", r"\bnot[ií]cia falsa", r"\bmedia ban\b",
            r"\bfake news\b",
        ],
        "children": [
            {
                "id": "media-disinfo",
                "name": "Disinformation",
                "blurb": "Fake news, propaganda, and information warfare.",
                "patterns": [r"\bdisinfo", r"\bmisinfo", r"\bfake news\b", r"\bnot[ií]cia falsa"],
            },
            {
                "id": "media-press",
                "name": "Press & speech",
                "blurb": "Press freedom, censorship, and media fights.",
                "patterns": [r"\bcensur", r"\bpress freedom\b", r"\bmedia ban\b", r"\bpress corps\b"],
            },
        ],
    },
    {
        "id": "topic-crime",
        "name": "Crime & justice",
        "facet": "topic",
        "blurb": "Policing, corruption, and criminal law.",
        "patterns": [
            r"\bcrime\b", r"\bpolice\b", r"\bcorrup", r"\bmurder\b",
            r"\bviol[eê]ncia\b", r"\bpol[ií]cia\b",
        ],
        "children": [
            {
                "id": "crime-policing",
                "name": "Policing & violence",
                "blurb": "Police, violence, and public safety.",
                "patterns": [r"\bpolice\b", r"\bmurder\b", r"\bassault\b", r"\bviol[eê]ncia\b", r"\bpol[ií]cia\b"],
            },
            {
                "id": "crime-corruption-courts",
                "name": "Corruption & criminal courts",
                "blurb": "Corruption cases, trials, and criminal courts.",
                "patterns": [r"\bcorrup", r"\btrial\b", r"\bprosecut", r"\bverdict\b"],
            },
        ],
    },
    {
        "id": "topic-migration",
        "name": "Migration & borders",
        "facet": "topic",
        "blurb": "Immigration, asylum, borders, and demographic politics.",
        "patterns": [
            r"\bmigration\b", r"\bimmigration\b", r"\basylum\b", r"\brefugee",
            r"\bborder\b", r"\bmigrant", r"\bimigra",
        ],
        "children": [
            {
                "id": "mig-asylum-refugees",
                "name": "Asylum & refugees",
                "blurb": "Asylum claims and refugee policy.",
                "patterns": [r"\basylum\b", r"\brefugee", r"\brefugiad"],
            },
            {
                "id": "mig-borders-deportation",
                "name": "Borders & deportation",
                "blurb": "Border enforcement and deportations.",
                "patterns": [r"\bborder\b", r"\bdeport", r"\bvisa\b"],
            },
        ],
    },
    {
        "id": "topic-diplomacy",
        "name": "Diplomacy & global order",
        "facet": "topic",
        "blurb": "Summits, alliances, foreign policy, and multilateral forums.",
        "patterns": [
            r"\bdiplomacy\b", r"\bforeign policy\b", r"\bunited nations\b",
            r"\bg20\b", r"\bg7\b", r"\bgeopolitic", r"\bdiplomacia\b",
            r"\bambassador\b", r"\bsummit\b", r"\bopep\b", r"\bopec\b",
        ],
        "children": [
            {
                "id": "dip-summits",
                "name": "Summits & forums",
                "blurb": "G20, G7, UN, and multilateral meetings.",
                "patterns": [r"\bg20\b", r"\bg7\b", r"\bunited nations\b", r"\bsummit\b", r"\bopep\b", r"\bopec\b"],
            },
            {
                "id": "dip-foreign-policy",
                "name": "Foreign policy",
                "blurb": "Bilateral diplomacy and foreign-policy strategy.",
                "patterns": [r"\bforeign policy\b", r"\bdiplomacy\b", r"\bambassador\b", r"\bdiplomacia\b", r"\bgeopolitic"],
            },
        ],
    },
    {
        "id": "topic-education",
        "name": "Education, work & daily life",
        "facet": "topic",
        "blurb": "Schools, universities, workplaces, and everyday practical life.",
        "patterns": [
            r"\beducation\b", r"\beduca[cç]", r"\buniversity\b", r"\buniversidade\b",
            r"\bschool\b", r"\bescola\b", r"\bworkplace\b", r"\btrabalho\b",
            r"\bjob\b", r"\bcarr[eé]er\b", r"\bremote work\b", r"\begg freez",
            r"\bfertility\b",
        ],
        "children": [
            {
                "id": "edu-schools",
                "name": "Schools & universities",
                "blurb": "Education systems, campuses, and learning.",
                "patterns": [
                    r"\beducation\b", r"\beduca[cç]", r"\buniversity\b",
                    r"\buniversidade\b", r"\bschool\b", r"\bescola\b",
                ],
            },
            {
                "id": "edu-work-life",
                "name": "Work & life logistics",
                "blurb": "Jobs, careers, and everyday life decisions.",
                "patterns": [
                    r"\bworkplace\b", r"\btrabalho\b", r"\bjob\b", r"\bcarr[eé]er\b",
                    r"\bremote work\b", r"\begg freez", r"\bfertility\b",
                ],
            },
        ],
    },
    {
        "id": "topic-religion",
        "name": "Religion & belief",
        "facet": "topic",
        "blurb": "Faith, churches, Islam, Christianity, and religious politics.",
        "patterns": [
            r"\breligion\b", r"\breligi[aã]o\b", r"\bchurch\b", r"\bigreja\b",
            r"\bislam\b", r"\bmuslim\b", r"\bcrist", r"\bchristian",
            r"\bjewish\b", r"\bjudaism\b", r"\bevangelical", r"\bfaith\b",
            r"\bprotestant", r"\bcatholic", r"\bcat[oó]lic",
        ],
        "children": [
            {
                "id": "rel-christianity",
                "name": "Christianity",
                "blurb": "Churches, Catholicism, Protestantism, and evangelicals.",
                "patterns": [
                    r"\bchurch\b", r"\bigreja\b", r"\bcrist", r"\bchristian",
                    r"\bevangelical", r"\bprotestant", r"\bcatholic", r"\bcat[oó]lic",
                ],
            },
            {
                "id": "rel-islam-judaism",
                "name": "Islam & Judaism",
                "blurb": "Islam, Muslim communities, and Judaism.",
                "patterns": [r"\bislam\b", r"\bmuslim\b", r"\bjewish\b", r"\bjudaism\b"],
            },
        ],
    },
    {
        "id": "topic-weather",
        "name": "Weather & disasters",
        "facet": "topic",
        "blurb": "Hurricanes, floods, fires, and extreme weather.",
        "patterns": [
            r"\bhurricane\b", r"\bflood", r"\bwildfire\b", r"\bearthquake\b",
            r"\bstorm\b", r"\bcyclone\b", r"\benchente", r"\bel ni[nñ]o\b",
        ],
        "children": [
            {
                "id": "wx-storms",
                "name": "Storms & hurricanes",
                "blurb": "Hurricanes, cyclones, and major storms.",
                "patterns": [r"\bhurricane\b", r"\bstorm\b", r"\bcyclone\b", r"\btyphoon\b"],
            },
            {
                "id": "wx-flood-fire",
                "name": "Floods & fires",
                "blurb": "Flooding and wildfire disasters.",
                "patterns": [r"\bflood", r"\bwildfire\b", r"\benchente", r"\binc[eê]ndio", r"\bel ni[nñ]o\b"],
            },
        ],
    },
]

PARENTS: list[dict] = PLACE_PARENTS + TOPIC_PARENTS


def compile_parent(parent: dict) -> dict:
    return {
        **parent,
        "re": [re.compile(p, re.I) for p in parent["patterns"]],
        "children": [
            {
                **ch,
                "re": [re.compile(p, re.I) for p in ch["patterns"]],
            }
            for ch in parent.get("children") or []
        ],
    }


def matches(pats: list[re.Pattern], text: str) -> bool:
    return any(p.search(text) for p in pats)


def body_for_episode(i: int, notes: dict, full_texts: dict[str, str]) -> tuple[str, str]:
    """Return (body_text, evidence_src) preferring full store over slim notes."""
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
    pats: list[re.Pattern],
) -> None:
    if body and matches(pats, body):
        if src in ("transcript", "stt"):
            evidence[tid]["transcript"] += 1
        else:
            evidence[tid]["notes"] += 1
    elif matches(pats, title_show):
        evidence[tid]["title"] += 1


def tag_all(
    episodes: list[dict],
    notes: dict,
    full_texts: dict[str, str] | None = None,
) -> tuple[list[list[str]], dict]:
    compiled = [compile_parent(p) for p in PARENTS]
    counts: Counter = Counter()
    samples: dict[str, list] = defaultdict(list)
    by_year: dict[str, Counter] = defaultdict(Counter)
    evidence: dict[str, Counter] = defaultdict(Counter)
    tagged: list[list[str]] = []
    full_texts = full_texts or {}

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
        hay = f"{title}\n{show}\n{safe_folder}\n{body}"
        title_show = f"{title}\n{show}\n{safe_folder}"
        hits: list[str] = []

        for parent in compiled:
            facet = parent.get("facet") or "topic"
            child_hits: list[str] = []

            if facet == "place":
                # 3B: place parent only when a clear geo cue appears in
                # title / show / safe folder — not solely from body text.
                if not matches(parent["re"], title_show):
                    continue
                for ch in parent["children"]:
                    if matches(ch["re"], hay):
                        child_hits.append(ch["id"])
                        record_evidence(
                            evidence, ch["id"], body=body, src=src,
                            title_show=title_show, pats=ch["re"],
                        )
                hits.append(parent["id"])
                hits.extend(child_hits)
                record_evidence(
                    evidence, parent["id"], body=body, src=src,
                    title_show=title_show, pats=parent["re"],
                )
            else:
                # Topic: parent if own patterns or any child matches.
                for ch in parent["children"]:
                    if matches(ch["re"], hay):
                        child_hits.append(ch["id"])
                        record_evidence(
                            evidence, ch["id"], body=body, src=src,
                            title_show=title_show, pats=ch["re"],
                        )
                parent_hit = bool(child_hits) or matches(parent["re"], hay)
                if not parent_hit:
                    continue
                hits.append(parent["id"])
                hits.extend(child_hits)
                record_evidence(
                    evidence, parent["id"], body=body, src=src,
                    title_show=title_show, pats=parent["re"],
                )

            for tid in [parent["id"], *child_hits]:
                counts[tid] += 1
                by_year[tid][str(ep.get("y") or "")] += 1
                if len(samples[tid]) < 8:
                    samples[tid].append(
                        {"i": i, "e": title, "p": ep.get("p"), "d": ep.get("d")}
                    )

        seen: set[str] = set()
        uniq: list[str] = []
        for h in hits:
            if h not in seen:
                seen.add(h)
                uniq.append(h)
        tagged.append(uniq)

    catalog = []
    for parent in compiled:
        pid = parent["id"]
        children = []
        for ch in parent["children"]:
            ev = dict(evidence.get(ch["id"]) or {})
            children.append(
                {
                    "id": ch["id"],
                    "name": ch["name"],
                    "blurb": ch["blurb"],
                    "facet": parent.get("facet") or "topic",
                    "parentId": pid,
                    "count": int(counts.get(ch["id"], 0)),
                    "byYear": dict(sorted(by_year[ch["id"]].items())),
                    "evidence": {
                        "title": int(ev.get("title", 0)),
                        "notes": int(ev.get("notes", 0)),
                        "transcript": int(ev.get("transcript", 0)),
                    },
                    "samples": samples[ch["id"]],
                }
            )
        children.sort(key=lambda t: t["count"], reverse=True)
        evp = dict(evidence.get(pid) or {})
        catalog.append(
            {
                "id": pid,
                "name": parent["name"],
                "blurb": parent["blurb"],
                "facet": parent.get("facet") or "topic",
                "count": int(counts.get(pid, 0)),
                "byYear": dict(sorted(by_year[pid].items())),
                "evidence": {
                    "title": int(evp.get("title", 0)),
                    "notes": int(evp.get("notes", 0)),
                    "transcript": int(evp.get("transcript", 0)),
                },
                "samples": samples[pid],
                "children": children,
            }
        )
    catalog.sort(key=lambda t: t["count"], reverse=True)

    flat = []
    for p in catalog:
        flat.append({k: v for k, v in p.items() if k != "children"})
        for ch in p["children"]:
            flat.append(ch)

    tx_eps = sum(
        1
        for i in range(len(episodes))
        if (notes.get(str(i)) or {}).get("src") in ("transcript", "stt")
    )
    place_n = sum(1 for p in catalog if p.get("facet") == "place")
    topic_n = sum(1 for p in catalog if p.get("facet") == "topic")
    meta = {
        "totalEpisodes": len(episodes),
        "episodesWithTheme": sum(1 for t in tagged if t),
        "parentCount": len(catalog),
        "placeParentCount": place_n,
        "topicParentCount": topic_n,
        "childCount": sum(len(p["children"]) for p in catalog),
        "themeCount": len(flat),
        "episodesWithBodyText": sum(
            1
            for i in range(len(episodes))
            if body_for_episode(i, notes, full_texts)[0]
        ),
        "episodesWithTranscriptEvidence": int(tx_eps),
        "method": "orthogonal-place-topic-keyword-hierarchy",
        "note": (
            "Orthogonal facets: place parents (geo-gated) and topic parents "
            "(content). Ambiguous keywords like eleições/election attach to "
            "topics only; a place tag requires a clear geo cue. Episodes may "
            "carry both facets."
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
        f"parents={doc['meta']['parentCount']} "
        f"(place={doc['meta']['placeParentCount']} topic={doc['meta']['topicParentCount']}) "
        f"children={doc['meta']['childCount']} "
        f"tagged={doc['meta']['episodesWithTheme']}/{doc['meta']['totalEpisodes']}"
    )
    print("\nPlace parents:")
    for p in doc["themes"]:
        if p.get("facet") != "place":
            continue
        kids = ", ".join(f"{c['name']}({c['count']})" for c in p["children"][:4])
        print(f"  {p['name']}: {p['count']} | {kids}")
    print("\nTopic parents:")
    for p in doc["themes"]:
        if p.get("facet") != "topic":
            continue
        kids = ", ".join(f"{c['name']}({c['count']})" for c in p["children"][:4])
        print(f"  {p['name']}: {p['count']} | {kids}")


if __name__ == "__main__":
    main()
