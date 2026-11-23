"""Intel collector: free, always-on, no AI. Reads local and official sources about every place our stocks depend on,
tags each item with plain rules, and remembers everything in memory/intel/.

What it does each pass (every ~30 minutes):
  1. Local news by PLACE: the mines, mills, plants, reactors and countries in the nuclear fuel chain (Google News
     searches pinned to each place, so small local papers like northeastNOW or County 17 show up).
  2. Regional and official feeds: CBC Saskatchewan, World Nuclear News, the Federal Register, NRC event reports,
     Reddit (only if you add Reddit API keys).
  3. Rules, no AI: which stocks it touches, tags (disruption, regulation, contract, financing, politics, jobs, price,
     restart), numbers in the text, how NEW it is versus the last 30 days, and BURSTS (a place suddenly in the news).
  4. Hand-off: the few highest-scoring new items go to the team's news desk each run; the "Send everything to the
     team" button hands over the whole week.
Everything with a tag goes into desk memory with what the stock did afterwards, so the Research Lab can test it later.
"""
import calendar, datetime as dt, hashlib, html, json, os, re, time, urllib.parse, urllib.request
from collections import Counter, defaultdict

import feedparser

import desk_memory

ROOT = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(ROOT, "memory", "intel")
ITEMS, COUNTS = os.path.join(DIR, "items.json"), os.path.join(DIR, "counts.json")
UA = "Mozilla/5.0 SwingDesk personal research"

# place -> (search, stocks it touches). Searches are pinned to the place so the hits are local, not market chatter.
PLACES = {  # place: (search, stocks it touches, must-mention: any one entry; an entry's words must ALL appear; @nuke = a nuclear word)
    "Cigar Lake": ('"Cigar Lake"', ["CCJ"], [("cigar lake",)]),
    "McArthur River / Key Lake": ('"McArthur River" OR "Key Lake" uranium', ["CCJ"], [("mcarthur",), ("key lake",)]),
    "Athabasca Basin": ('"Athabasca Basin" OR "northern Saskatchewan" uranium', ["CCJ", "NXE", "DNN"], [("athabasca", "@nuke"), ("saskatchewan", "@nuke")]),
    "Saskatchewan wildfires": ('wildfire "northern Saskatchewan" OR "La Ronge" OR "Wollaston"', ["CCJ", "NXE", "DNN"], [("fire",), ("evacuat",)]),
    "Rook I / Arrow": ('"Rook I" OR NexGen Arrow OR "Patterson Lake"', ["NXE"], [("rook i",), ("nexgen",), ("patterson lake",)]),
    "Wheeler River / Phoenix": ('"Wheeler River" OR Denison Phoenix OR "McClean Lake"', ["DNN"], [("wheeler river",), ("denison",), ("mcclean",)]),
    "Port Hope / Blind River": ('"Port Hope" Cameco OR "Blind River" refinery', ["CCJ"], [("port hope",), ("blind river",), ("cameco",)]),
    "Westinghouse": ('Westinghouse nuclear AP1000', ["CCJ", "BWXT"], [("westinghouse", "@nuke"), ("ap1000",)]),
    "Kazakhstan": ('Kazatomprom OR Inkai OR "Kazakhstan uranium"', ["CCJ", "NXE", "UEC", "DNN"], [("kazatomprom",), ("inkai",), ("kazakhstan", "@nuke")]),
    "Niger": ('Niger uranium OR Arlit OR Orano Niger OR Somair', ["CCJ", "UEC"], [("niger", "@nuke"), ("arlit",), ("somair",), ("orano",)]),
    "Namibia": ('Namibia uranium OR "Langer Heinrich" OR Rossing OR Husab', ["CCJ"], [("namibia", "@nuke"), ("langer heinrich",), ("rossing",), ("rössing",), ("husab",)]),
    "Russia supply": ('Russia enriched uranium OR Tenex OR Rosatom ban', ["LEU", "CCJ"], [("russia", "uranium"), ("tenex",), ("rosatom",)]),
    "Piketon": ('Piketon OR "American Centrifuge" OR Centrus', ["LEU"], [("centrus",), ("american centrifuge",), ("piketon", "@nuke")]),
    "HALEU": ('HALEU', ["LEU", "BWXT"], [("haleu",)]),
    "Wyoming ISR": ('uranium Wyoming OR "Christensen Ranch" OR Irigaray OR "Smith Ranch"', ["UEC", "CCJ"], [("wyoming", "uranium"), ("christensen ranch",), ("irigaray",), ("smith ranch",)]),
    "South Texas ISR": ('uranium Texas Palangana OR "Burke Hollow" OR Goliad', ["UEC"], [("palangana",), ("burke hollow",), ("texas", "uranium")]),
    "White Mesa / Utah": ('"White Mesa" OR "Energy Fuels" Utah OR "Pinyon Plain"', ["UUUU"], [("white mesa",), ("energy fuels",), ("pinyon plain",)]),
    "Rare earths (Energy Fuels)": ('"Energy Fuels" rare earth OR Donald OR Toliara', ["UUUU"], [("energy fuels",)]),
    "Lynchburg / Erwin": ('BWXT Lynchburg OR "Nuclear Fuel Services" Erwin', ["BWXT"], [("bwxt",), ("nuclear fuel services",)]),
    "Naval reactors": ('naval nuclear propulsion OR "Naval Reactors" contract', ["BWXT"], [("naval", "nuclear"), ("submarine", "@nuke"), ("naval reactors",)]),
    "Crane / Three Mile Island": ('"Crane Clean Energy" OR "Three Mile Island" restart', ["CEG"], [("crane clean energy",), ("three mile island", "restart"), ("crane", "constellation")]),
    "Susquehanna": ('Susquehanna nuclear OR Talen Energy', ["TLN"], [("talen",), ("susquehanna", "nuclear")]),
    "Comanche Peak": ('"Comanche Peak" OR Vistra nuclear', ["VST"], [("comanche peak",), ("vistra",)]),
    "PJM grid": ('PJM capacity auction OR PJM prices', ["CEG", "TLN", "VST"], [("pjm",)]),
    "ERCOT grid": ('ERCOT prices OR ERCOT demand', ["VST"], [("ercot",)]),
    "Data-center nuclear deals": ('nuclear "power purchase agreement" data center', ["CEG", "VST", "TLN"], [("nuclear", "data cent")]),
    "Japan restarts": ('Kashiwazaki-Kariwa OR Japan reactor restart', ["CCJ"], [("kashiwazaki",), ("japan", "reactor"), ("japan", "nuclear")]),
    "China new builds": ('China approves nuclear reactors', ["CCJ"], [("china", "reactor"), ("china", "nuclear"), ("chinese", "nuclear")]),
    "Sprott trust": ('"Sprott Physical Uranium Trust"', ["CCJ", "NXE", "DNN", "UEC"], [("sprott", "uranium")]),
    "Uranium price": ('uranium spot price OR "uranium price"', ["CCJ", "NXE", "DNN", "UEC", "UUUU"], [("uranium",)]),
    "US policy": ('"Section 232" uranium OR DOE uranium reserve OR uranium executive order', ["CCJ", "UEC", "UUUU", "LEU"],
                  [("section 232", "uranium"), ("energy department", "uranium"), ("doe", "uranium"), ("uranium", "executive order"), ("uranium", "reserve")]),
    "Congress and laws": ('(Senate OR House OR Congress) (nuclear OR uranium) (bill OR act OR vote)', ["CCJ", "LEU", "CEG", "UEC", "UUUU"],
                          [("congress", "@nuke"), ("senate", "@nuke"), ("legislat", "@nuke"), ("bill", "nuclear power"), ("bill", "uranium"), ("bill", "reactor"), ("act", "uranium")]),
    "NRC decisions": ('"Nuclear Regulatory Commission" OR "NRC approves" OR "NRC license"', ["CEG", "VST", "TLN", "LEU", "BWXT"],
                      [("nuclear regulatory commission",), ("nrc", "@nuke")]),
    "Energy Department": ('"Department of Energy" (nuclear OR HALEU OR uranium OR reactor)', ["LEU", "BWXT", "CCJ", "UEC", "UUUU"],
                          [("department of energy", "@nuke"), ("energy department", "@nuke"), ("doe", "@nuke"), ("energy secretary", "@nuke")]),
    "White House and executive orders": ('"executive order" (nuclear OR uranium) OR "White House" nuclear', ["CCJ", "LEU", "UEC", "UUUU", "CEG"],
                                         [("executive order", "@nuke"), ("white house", "@nuke")]),
    "Tariffs and trade": ('uranium tariff OR "critical minerals" uranium OR uranium imports', ["CCJ", "UEC", "UUUU", "NXE", "DNN"],
                          [("tariff", "uranium"), ("critical mineral", "uranium"), ("import", "uranium")]),
    # --- the world: who is building, restarting and buying
    "India": ('India nuclear power OR NPCIL reactor OR India uranium', ["CCJ"], [("india", "@nuke"), ("npcil",)]),
    "South Korea": ('South Korea nuclear OR KHNP OR "Korea Hydro"', ["CCJ", "BWXT"], [("korea", "@nuke"), ("khnp",)]),
    "Europe new builds": ('nuclear reactor (Poland OR Czech OR Sweden OR Netherlands OR Romania OR Bulgaria OR Slovakia)', ["CCJ", "BWXT"],
                          [("poland", "@nuke"), ("czech", "@nuke"), ("sweden", "@nuke"), ("netherlands", "@nuke"), ("romania", "@nuke"), ("bulgaria", "@nuke"), ("slovakia", "@nuke")]),
    "France and UK": ('EDF nuclear OR "Sizewell C" OR "Hinkley Point" OR "Rolls-Royce SMR"', ["CCJ"],
                      [("edf", "@nuke"), ("sizewell",), ("hinkley",), ("rolls-royce", "smr"), ("france", "reactor")]),
    "Middle East": ('Saudi nuclear OR Barakah OR Akkuyu OR "El Dabaa"', ["CCJ", "LEU"],
                    [("saudi", "@nuke"), ("barakah",), ("akkuyu",), ("dabaa",), ("emirates", "@nuke")]),
    "Asia newcomers": ('nuclear power plan (Philippines OR Vietnam OR Indonesia OR Thailand OR Malaysia)', ["CCJ"],
                       [("philippines", "@nuke"), ("vietnam", "@nuke"), ("indonesia", "@nuke"), ("thailand", "@nuke"), ("malaysia", "@nuke")]),
    "Canada SMRs": ('Darlington SMR OR "Ontario Power Generation" nuclear OR "Bruce Power"', ["CCJ", "BWXT"],
                    [("darlington",), ("ontario power generation",), ("bruce power",)]),
    "Big tech power deals": ('(Microsoft OR Google OR Amazon OR Meta) nuclear deal', ["CEG", "VST", "TLN", "CCJ"],
                             [("microsoft", "@nuke"), ("google", "@nuke"), ("amazon", "@nuke"), ("meta", "nuclear")]),
    # --- defense and hostile uses: what can jolt the whole market
    "Iran": ('Iran uranium enrichment OR IAEA Iran', ["CCJ", "LEU"], [("iran", "@nuke")]),
    "North Korea": ('"North Korea" uranium OR "North Korea" nuclear', ["CCJ"], [("north korea", "@nuke")]),
    "War zones": ('Zaporizhzhia nuclear OR nuclear plant attack OR drone nuclear plant', ["CCJ", "CEG"],
                  [("zaporizhzhia",), ("chernobyl",), ("nuclear plant", "attack"), ("nuclear plant", "drone")]),
    "AUKUS and navies": ('AUKUS submarine OR nuclear submarine', ["BWXT"], [("aukus",), ("submarine", "nuclear")]),
    "Weapons programs": ('NNSA OR "nuclear weapons" OR plutonium pits OR "nuclear arsenal"', ["BWXT", "LEU"],
                         [("nnsa",), ("nuclear weapon",), ("plutonium",), ("nuclear arsenal",), ("warhead",)]),
    "Stockpiles and reserves": ('uranium reserve OR uranium stockpile OR "strategic uranium"', ["CCJ", "UEC", "UUUU"],
                                [("uranium", "reserve"), ("uranium", "stockpile")]),
    "Workers and jobs": ('(Cameco OR NexGen OR Denison OR Centrus OR "Energy Fuels" OR "Uranium Energy" OR BWXT) '
                         '(hiring OR layoffs OR jobs OR workers OR union OR strike)', [],
                         [("cameco",), ("nexgen",), ("denison",), ("centrus",), ("energy fuels",), ("uranium energy",), ("bwxt",)]),
}
NUKE = ("uranium", "nuclear", "reactor", "haleu", "enrich", "centrifuge", "atomic", "mine", "mining", "mill", "yellowcake", "u3o8")


def _has(low, term):
    if term == "@nuke":
        return any(_has(low, n) for n in NUKE)
    return re.search(r"(?<![a-z])" + re.escape(term), low) is not None


def relevant(text, must):
    low = text.lower()
    return not must or any(all(_has(low, t) for t in entry) for entry in must)
# whole feeds (no search): routed by the stock keywords in config
FEEDS = [
    ("CBC Saskatchewan", "https://www.cbc.ca/webfeed/rss/rss-canada-saskatchewan", True),
    ("World Nuclear News", "https://www.world-nuclear-news.org/rss", False),
    ("Federal Register (uranium)", "https://www.federalregister.gov/api/v1/documents.rss?conditions%5Bterm%5D=uranium", False),
    ("Federal Register (nuclear)", "https://www.federalregister.gov/api/v1/documents.rss?conditions%5Bterm%5D=nuclear+reactor", False),
    ("NRC event reports", "https://www.nrc.gov/public-involve/rss?feed=event", False),
]
LOCAL_FILTER = ("uranium", "nuclear", "cameco", "orano", "nexgen", "denison", "mine", "wildfire", "athabasca", "la ronge",
                "wollaston", "key lake", "cigar lake", "mcarthur")
SUBREDDITS = ["UraniumSqueeze", "uraniumstocks", "nuclear"]

TAGS = {
    "disruption": ("shutdown", "shut down", "halt", "suspend", "flood", "wildfire", "fire", "evacuat", "strike", "outage",
                   "accident", "leak", "scram", "tripped", "injur", "closure", "closes", "curtail", "delay", "force majeure"),
    "regulation": ("nrc", "license", "licence", "permit", "approv", "ban", "sanction", "tariff", "section 232",
                   "executive order", "legislat", "bill ", "ruling", "cnsc", "regulator"),
    "contract": ("contract", "agreement", "supply deal", "offtake", "award", "ppa", "purchase agreement", "partnership", "mou"),
    "financing": ("offering", "financing", "private placement", "bought deal", "raises", "notes due", "convertible", "atm program"),
    "politics": ("coup", "junta", "election", "nationaliz", "export", "border", "military", "government", "minister"),
    "jobs": ("hiring", "jobs", "layoff", "workers", "union", "workforce", "staff"),
    "production": ("production", "output", "guidance", "pounds", "tonnes", "mined", "milled", "ramp"),
    "price": ("spot price", "term price", "per pound", "/lb", "price of uranium", "uranium price"),
    "restart": ("restart", "new reactor", "smr", "construction", "build", "relicens"),
    "defense": ("military", "navy", "submarine", "weapon", "missile", "nnsa", "aukus", "defense", "defence", "warhead", "pentagon"),
    "geopolitics": ("war", "attack", "invasion", "enrichment", "iaea", "nonproliferation", "sanction", "drone strike", "ceasefire"),
    "opposition": ("protest", "lawsuit", "court", "appeal", "opposition", "oppose", "challenge"),
}
WEIGHT = {"disruption": 2.0, "regulation": 1.5, "contract": 1.3, "financing": 1.2, "politics": 1.0, "production": 0.8,
          "price": 0.8, "restart": 0.7, "opposition": 0.7, "jobs": 0.6, "defense": 1.0, "geopolitics": 1.3}
MEMORY_TAGS = ("disruption", "regulation", "contract", "financing", "politics", "production", "opposition", "defense", "geopolitics")
BIG_OUTLETS = ("reuters", "bloomberg", "yahoo", "cnbc", "marketwatch", "seeking alpha", "motley fool", "zacks", "tradingview",
               "investing.com", "benzinga", "kalkine", "ad-hoc-news", "blockchain news", "mlq", "devdiscourse", "marketbeat", "stocktitan", "tipranks", "insidermonkey", "globe and mail", "financial post", "barron", "msn", "nasdaq", "simply wall")
NUM = re.compile(r"(?:US)?\$?\d[\d,]*(?:\.\d+)?\s?(?:%|percent|million|billion|mlbs|lbs|pounds|tonnes|tons|tu\b|mw\b|gw\b|/lb|per pound)", re.I)
STOP = set("the a an and or of to in on for with at by from as is are was be its it this that after over new says inc corp "
           "co will has have than into about more could would".split())


def _load(p, d):
    try:
        return json.load(open(p))
    except Exception:
        return d


def _save(p, o):
    os.makedirs(DIR, exist_ok=True)
    json.dump(o, open(p, "w"), indent=0)


def _clean(s, n=400):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()[:n]


def _words(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2 and w not in STOP}


def _ts(e):
    for k in ("published_parsed", "updated_parsed"):
        if e.get(k):
            return calendar.timegm(e[k])
    return int(time.time())


def _feed(url):
    try:
        return feedparser.parse(url, agent=UA).entries
    except Exception:
        return None


def _gnews(q, days=3):
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": f"{q} when:{days}d", "hl": "en-US", "gl": "US", "ceid": "US:en"})


def _reddit():
    cid, sec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_SECRET")
    if not (cid and sec):
        return []
    import base64
    try:
        req = urllib.request.Request("https://www.reddit.com/api/v1/access_token", data=b"grant_type=client_credentials",
                                     headers={"User-Agent": "SwingDesk/1.0 personal research",
                                              "Authorization": "Basic " + base64.b64encode(f"{cid}:{sec}".encode()).decode()})
        tok = json.load(urllib.request.urlopen(req, timeout=20))["access_token"]
    except Exception as e:
        print("reddit auth failed", e); return []
    out = []
    for sub in SUBREDDITS:
        try:
            req = urllib.request.Request(f"https://oauth.reddit.com/r/{sub}/new?limit=40",
                                         headers={"User-Agent": "SwingDesk/1.0 personal research", "Authorization": f"bearer {tok}"})
            for c in json.load(urllib.request.urlopen(req, timeout=20))["data"]["children"]:
                d = c["data"]
                out.append({"title": _clean(d.get("title"), 200), "summary": _clean(d.get("selftext"), 300),
                            "link": "https://reddit.com" + d.get("permalink", ""), "ts": int(d.get("created_utc", time.time())),
                            "outlet": f"r/{sub}", "place": "Reddit", "score_ups": d.get("ups", 0)})
        except Exception as e:
            print("reddit", sub, e)
    return out


def _route(text, cfg, base):
    low = f" {text.lower()} "
    kw = (cfg.get("news_sources") or {}).get("keywords", {})
    hits = [t for t in cfg["tickers"] if any(k in low for k in kw.get(t, [])) or f" {t.lower()} " in low]
    return list(dict.fromkeys([t for t in base if t in cfg["tickers"]] + hits))


CHATTER = ("price prediction", "stock target", "price target", "why are", "why is", "valuation", "share price", "stock price",
           "shares fall", "shares rise", "stock jumps", "stock falls", "should you buy", "buy now", "top stocks", "etf (")
EXCLUDE = ("nexgen cloud", "nexgen solutions", "westinghouse electric appliance", "cagr", "market to reach", "market size",
           "market report", "market research", "forecast to 20")


def _tags(text):
    low = text.lower()
    return [t for t, kws in TAGS.items() if any(_has(low, k.strip()) for k in kws)]


# ------------------------------------------------------------------ one pass
def collect(cfg, max_age_days=4):
    """Fetch every source once. Returns (raw items, source health)."""
    raw, health = [], {}
    generic = ("Uranium price", "US policy", "Sprott trust", "Workers and jobs")  # broad searches last: specific places keep their stories
    for place, (q, base, must) in sorted(PLACES.items(), key=lambda kv: kv[0] in generic):
        ents = _feed(_gnews(q))
        health[place] = None if ents is None else len(ents)
        for e in ents or []:
            title = _clean(e.get("title"), 220)
            outlet = _clean((e.get("source") or {}).get("title", "")) or (title.rsplit(" - ", 1)[-1] if " - " in title else "")
            if not relevant(title.rsplit(" - ", 1)[0] + " " + _clean(e.get("summary")), must):
                continue
            raw.append({"title": title.rsplit(" - ", 1)[0] if outlet and title.endswith(outlet) else title, "outlet": outlet,
                        "summary": "", "link": e.get("link"), "ts": _ts(e), "place": place, "base": base})
        time.sleep(0.4)
    for name, url, local in FEEDS:
        ents = _feed(url)
        health[name] = None if ents is None else len(ents)
        for e in ents or []:
            title, summ = _clean(e.get("title"), 220), _clean(e.get("summary"))
            if local and not any(k in (title + " " + summ).lower() for k in LOCAL_FILTER):
                continue
            raw.append({"title": title, "outlet": name, "summary": summ, "link": e.get("link"), "ts": _ts(e), "place": name, "base": []})
    rd = _reddit()
    if rd:
        health["Reddit"] = len(rd)
        raw += [dict(r, base=[]) for r in rd]
    cut = time.time() - max_age_days * 86400
    return [r for r in raw if r["ts"] >= cut], health


def run(cfg, st):
    """One collector pass. Returns the list of NEW items (already tagged, scored and stored)."""
    import reactors
    store = _load(ITEMS, [])
    known = {i["id"] for i in store}
    recent = [i for i in store if i["ts"] > time.time() - 30 * 86400]
    raw, health = collect(cfg)
    unit_owner = reactors.UNIT_OWNER
    new = []
    for r in sorted(raw, key=lambda x: x["ts"]):
        iid = hashlib.sha1((r.get("link") or r["title"]).encode()).hexdigest()[:16]
        if iid in known or not r["title"]:
            continue
        known.add(iid)
        text = f"{r['title']} {r.get('summary', '')}"
        if any(x in text.lower() for x in EXCLUDE + tuple((cfg.get("news_sources") or {}).get("exclude", []))):
            continue
        base = list(r.get("base") or [])
        if r["outlet"] == "NRC event reports":  # titles are "58540 - <licensee>": only keep our owners' plants
            site = r["title"].split(" - ", 1)[-1].lower()
            base = [o for u, o in unit_owner.items() if u.rsplit(" ", 1)[0].lower() in site][:1]
            if not base:
                continue
        tickers = _route(text, cfg, base)
        w = _words(r["title"])
        best, echo_of = 0.0, None
        for o in recent[-3000:]:
            j = len(w & set(o["w"])) / max(1, len(w | set(o["w"])))
            if j > best:
                best, echo_of = j, o["id"]
        tags = _tags(text)
        nums = list(dict.fromkeys(m.group(0).strip() for m in NUM.finditer(text)))[:6]
        local = bool(r["outlet"]) and not any(b in r["outlet"].lower() for b in BIG_OUTLETS)
        novelty = round(1 - best, 2)
        chatter = any(c in text.lower() for c in CHATTER)
        if chatter:
            tags = [t for t in tags if t not in ("regulation", "contract", "disruption")] + ["market_chatter"]
        score = round(1 + sum(WEIGHT.get(t, 0) for t in tags) + 0.5 * bool(nums) + (1.0 if local else 0) + 2 * novelty
                      + (0.5 if tickers else -1) - (1.5 if chatter else 0), 2)
        it = {"id": iid, "date": str(dt.datetime.fromtimestamp(r["ts"], dt.timezone.utc).date()), "ts": r["ts"], "title": r["title"],
              "summary": r.get("summary", "")[:300], "outlet": r["outlet"], "link": r.get("link"), "place": r["place"],
              "tickers": tickers, "tags": tags, "numbers": nums, "local": local, "novelty": novelty, "score": score,
              "echo_of": echo_of if best >= 0.6 else None, "w": sorted(w)[:25]}
        new.append(it); recent.append(it)
    store += new
    store = [i for i in store if i["ts"] > time.time() - 120 * 86400][-8000:]
    _save(ITEMS, store)
    # daily story counts per place (echoes of the same story count once): the raw material for burst detection
    counts = _load(COUNTS, {})
    for it in new:
        if not it["echo_of"]:
            c = counts.setdefault(it["date"], {})
            c[it["place"]] = c.get(it["place"], 0) + 1
    for d in sorted(counts)[:-400]:
        del counts[d]
    _save(COUNTS, counts)
    # long-term memory: tagged items about our stocks (outcomes get filled in by the daily memory job)
    for it in new:
        mt = [t for t in it["tags"] if t in MEMORY_TAGS]
        if it["tickers"] and mt and not it["echo_of"] and it["score"] >= 4:
            for t in it["tickers"][:2]:
                desk_memory.add_event(t, it["title"], f"intel_{mt[0]}", it["date"], f"Intel: {it['outlet'] or it['place']}")
    st["intel_health"] = {"at": time.strftime("%Y-%m-%d %H:%M"), "sources": health,
                          "failed": [k for k, v in health.items() if v is None]}
    return new


def bursts(today=None, min_today=3, ratio=3.0):
    """Places suddenly in the news: today's distinct stories vs the place's normal day over the past 30 days."""
    counts = _load(COUNTS, {})
    today = str(today or dt.datetime.now(dt.timezone.utc).date())
    past = [d for d in sorted(counts) if d < today][-30:]
    if len(past) < 14:  # no baseline yet: a "burst" needs two weeks of normal days to compare against
        return []
    out = []
    for place, n in (counts.get(today) or {}).items():
        base = sum(counts[d].get(place, 0) for d in past) / max(1, len(past))
        if n >= min_today and n >= ratio * base + 1:
            out.append({"place": place, "today": n, "normal": round(base, 2), "tickers": PLACES.get(place, ("", [], []))[1]})
    return sorted(out, key=lambda b: -b["today"])


def handoff(st, max_n=5, min_score=4.5):
    """The best new items for the team's news desk (each item is handed over once)."""
    done = set(st.setdefault("intel_handed", []))
    pick = [i for i in _load(ITEMS, []) if i["id"] not in done and i["tickers"] and not i["echo_of"]
            and i["score"] >= min_score and i["ts"] > time.time() - 36 * 3600]
    pick = sorted(pick, key=lambda i: -i["score"])[:max_n]
    st["intel_handed"] = (list(done) + [i["id"] for i in pick])[-3000:]
    return [{"id": "intel-" + i["id"], "ticker": i["tickers"][0], "also": i["tickers"][1:],
             "source": f"Local intel: {i['outlet'] or i['place']} ({i['place']})", "title": i["title"],
             "summary": (i["summary"] + (" Numbers: " + ", ".join(i["numbers"]) if i["numbers"] else "")).strip(),
             "link": i["link"], "ts": i["ts"]} for i in pick]


def _slim(i):
    return {k: i.get(k) for k in ("date", "title", "outlet", "place", "tickers", "tags", "numbers", "score", "link")}


def digest(days=7, top=40):
    """Everything worth reading from the last `days`, for the 'Send everything to the team' button."""
    import reactors
    cut = time.time() - days * 86400
    items = [i for i in _load(ITEMS, []) if i["ts"] >= cut and not i["echo_of"]]
    by_place = Counter(i["place"] for i in items)
    snap = _load(reactors.STATUS, {})
    return {"days": days, "stories": len(items), "stories_by_place": dict(by_place.most_common(20)),
            "bursts_today": bursts(), "reactors": {k: snap.get(k) for k in ("date", "us_fleet_running_pct", "owners", "open_outages")},
            "top_items": [_slim(i) for i in sorted(items, key=lambda i: -i["score"])[:top]],
            "memory_playbooks_for_local_news": {k: v for k, v in desk_memory.all_playbooks(None).items() if k.startswith("intel_") or k in ("reactor_outage", "news_burst")}}


def view(st):
    """Small summary for the page."""
    import reactors
    items = _load(ITEMS, [])
    cut = time.time() - 7 * 86400
    wk = [i for i in items if i["ts"] >= cut and not i["echo_of"]]
    snap = _load(reactors.STATUS, {})
    st["intel_view"] = {"updated": time.strftime("%Y-%m-%d %H:%M"), "total": len(items), "week": len(wk),
                        "places": dict(Counter(i["place"] for i in wk).most_common(12)),
                        "bursts": bursts(), "health": st.get("intel_health"),
                        "reactors": {k: snap.get(k) for k in ("date", "us_fleet_running_pct", "owners", "open_outages")},
                        "top": [_slim(i) for i in sorted(wk, key=lambda i: (-i["score"], -i["ts"]))[:30]]}
    return st["intel_view"]


if __name__ == "__main__":
    import sys
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    st = {}
    n = run(cfg, st)
    print(len(n), "new;", "failed:", st["intel_health"]["failed"])
    for i in sorted(n, key=lambda i: -i["score"])[:25]:
        print(f"{i['score']:5.2f} {i['place'][:18]:18s} {','.join(i['tickers'])[:14]:14s} {'/'.join(i['tags'])[:30]:30s} {i['title'][:80]} [{i['outlet'][:20]}]")
    print("bursts", bursts())
