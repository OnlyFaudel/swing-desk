"""News scout feeds: Yahoo Finance RSS, Google News RSS, SEC EDGAR filings."""
import hashlib, re, html, time, calendar
import urllib.parse, urllib.request
import feedparser

UA = "SwingDesk personal research bot (github actions)"
SEC_FORMS = {"8-K", "6-K", "10-Q", "10-K", "40-F", "S-3", "S-3ASR", "424B5", "424B2", "SC 13D", "SC 13G", "F-10"}


def _clean(s, n=400):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()[:n]


def _id(link, title):
    return hashlib.sha1((link or title).encode()).hexdigest()[:16]


def _ts(e):
    for k in ("published_parsed", "updated_parsed"):
        if e.get(k):
            return calendar.timegm(e[k])
    return int(time.time())


def sec_filings(t, cik, cfg):
    """Company filings straight from the SEC (8-K, 6-K, 10-Q, offerings...)."""
    import json, urllib.request, datetime as dt
    ua = f"SwingDesk personal research {cfg.get('sec_contact_email') or 'swingdesk.bot@gmail.com'}"
    try:
        req = urllib.request.Request(f"https://data.sec.gov/submissions/CIK{cik}.json", headers={"User-Agent": ua})
        r = json.load(urllib.request.urlopen(req, timeout=20))["filings"]["recent"]
    except Exception as e:
        print("sec error", t, e)
        return []
    out = []
    for i in range(min(40, len(r["form"]))):
        form = r["form"][i]
        if form.upper() not in SEC_FORMS:
            continue
        acc = r["accessionNumber"][i].replace("-", "")
        link = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{r['primaryDocument'][i]}"
        when = r.get("acceptanceDateTime", [None] * 99)[i] or r["filingDate"][i]
        try:
            ts = int(dt.datetime.fromisoformat(when.replace("Z", "+00:00")).timestamp())
        except Exception:
            ts = int(dt.datetime.fromisoformat(r["filingDate"][i]).timestamp())
        desc = r["primaryDocDescription"][i] or ""
        items_ = r.get("items", [""] * 99)[i] if r.get("items") else ""
        out.append({"id": _id(link, form), "ticker": t, "source": "SEC filing",
                    "title": f"SEC {form} filed{(' (items ' + items_ + ')') if items_ else ''}: {desc}".strip(),
                    "summary": f"{form} {items_}", "link": link, "ts": ts})
    return out


def _route(text, cfg):
    """Which of our stocks a headline is about (keyword match), in order; [] = not ours or junk."""
    low = f" {text.lower()} "
    ns = cfg.get("news_sources") or {}
    if any(x in low for x in ns.get("exclude", [])):
        return []
    kw = ns.get("keywords", {})
    return [t for t in cfg["tickers"] if any(k in low for k in kw.get(t, [])) or f" {t.lower()} " in low]


def _parse(src, url, limit=25):
    try:
        fp = feedparser.parse(url, agent=UA)
    except Exception as e:
        print("feed error", src, e)
        return []
    return [{"title": _clean(e.get("title"), 200), "summary": _clean(e.get("summary")), "link": e.get("link"), "ts": _ts(e)}
            for e in fp.entries[:limit]]


def fetch_news(cfg, lanes=("fast", "slow")):
    """fast lane (every run): each stock's Yahoo feed, SEC filings, Cameco's press room.
    slow lane (every ~10 min): nuclear-industry feeds, Google News topic searches, related companies' feeds."""
    items = []
    ns = cfg.get("news_sources") or {}
    slow = "slow" in lanes
    # industry channels (nuclear news, the regulator, the Federal Register, company press rooms): routed by keyword
    for src, url in ns.get("industry", []):
        if not slow and src not in ns.get("fast_industry", []):
            continue
        for e in _parse(src, url, 40):
            hit = _route(e["title"] + " " + e["summary"], cfg)
            if hit:
                items.append({"id": _id(e["link"], e["title"]), "ticker": hit[0], "also": hit[1:], "source": src, **e})
    # topic searches per stock (uranium price, HALEU, reactor restarts...)
    for t, topics in (ns.get("topics", {}).items() if slow else []):
        if t not in cfg["tickers"]:
            continue
        for q in topics:
            url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q + " when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
            for e in _parse(f"Google News: {q}", url, 15):
                if t in _route(e["title"] + " " + e["summary"], cfg):  # must really be about this stock's world
                    items.append({"id": _id(e["link"], e["title"]), "ticker": t, "source": f"Google News: {q}", **e})
    for t in cfg["tickers"]:
        feeds = [
            ("Yahoo Finance", f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={t}&region=US&lang=en-US"),
            ("Google News", "https://news.google.com/rss/search?" + urllib.parse.urlencode(
                {"q": cfg["news_query"][t] + " when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"})),
        ]
        # supply-chain read-through: related companies' headlines, scored for what they mean for t
        for ctx in (cfg.get("context_tickers", {}).get(t, []) if slow else []):
            feeds.append((f"Yahoo ({ctx}, related to {t})", f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ctx}&region=US&lang=en-US"))
        cik = cfg["sec_cik"].get(t)
        if cik:
            items += sec_filings(t, cik, cfg)
        for src, url in feeds:
            try:
                fp = feedparser.parse(url, agent=UA)
            except Exception as e:
                print("feed error", src, t, e)
                continue
            for e in fp.entries[:25]:
                title = _clean(e.get("title"), 200)
                summ = _clean(e.get("summary"))
                name = cfg["news_query"].get(t, "").split('"')[1].lower() if '"' in cfg["news_query"].get(t, "") else t.lower()
                txt = f" {title} {summ} ".lower()
                if ns.get("keywords") and (any(x in txt for x in ns.get("exclude", [])) or not (name in txt or f" {t.lower()} " in txt or t in title or _route(txt, cfg))):
                    continue  # generic page or another company's story (e.g. an Oklo headline on LEU's feed)
                items.append({"id": _id(e.get("link"), title), "ticker": t, "source": src,
                              "title": title, "summary": summ, "link": e.get("link"), "ts": _ts(e)})
    # newest first, de-duplicate by near-identical title
    seen, out, per = set(), [], {}
    for it in sorted(items, key=lambda x: -x["ts"]):
        if len(out) >= ns.get("max_items_per_run", 10**6):
            break
        if per.get(it["source"], 0) >= ns.get("per_source_cap", 10**6):
            continue  # no single feed crowds out the others
        per[it["source"]] = per.get(it["source"], 0) + 1
        key = re.sub(r"[^a-z0-9]", "", it["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def new_items(cfg, state, max_age_hours=36):
    seen = set(state.setdefault("seen_news", []))
    now = time.time()
    slow_every = (cfg.get("news_sources") or {}).get("slow_lane_minutes", 10) * 60
    lanes = ("fast", "slow") if now - state.get("news_slow_at", 0) >= slow_every else ("fast",)
    if "slow" in lanes:
        state["news_slow_at"] = now
    fresh = [i for i in fetch_news(cfg, lanes) if i["id"] not in seen and now - i["ts"] < max_age_hours * 3600]
    state["seen_news"] = (list(seen) + [i["id"] for i in fresh])[-3000:]
    return fresh


def sec_map(cache):
    """ticker -> (10-digit CIK, company name) from the SEC, cached for a week."""
    import json, urllib.request, time as _t
    m = cache.get("sec_map")
    if m and _t.time() - m.get("t", 0) < 7 * 86400:
        return m["map"]
    req = urllib.request.Request("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": "SwingDesk research swingdesk.bot@gmail.com"})
    d = json.load(urllib.request.urlopen(req, timeout=30))
    mp = {v["ticker"]: [str(v["cik_str"]).zfill(10), v["title"]] for v in d.values()}
    cache["sec_map"] = {"t": _t.time(), "map": mp}
    return mp


def ticker_cfg(cfg, tickers, cache):
    """Config view for news/intel covering this week's lineup (any ticker)."""
    try:
        mp = sec_map(cache)
    except Exception:
        mp = {}
    q, cik = {}, {}
    for t in tickers:
        name = (mp.get(t) or [None, t])[1]
        import re as _re
        short = _re.sub(r"\b(corp(oration)?|inc|co|ltd|plc|holdings?|company|technologies|group|n\.?v\.?|s\.?a\.?)\.?$", "", name.title().replace(",", ""), flags=_re.I).strip()
        short = _re.sub(r"\s+(Co|Ltd|Inc|Corp)\.?$", "", short).strip()
        q[t] = f'"{short}" OR "{t} stock"'
        if mp.get(t):
            cik[t] = mp[t][0]
    return dict(cfg, tickers=list(tickers), news_query=q, sec_cik=cik)


def stocktwits(t):
    """Public StockTwits stream: last ~30 messages, with the bullish/bearish tags people chose."""
    import json as _j
    req = urllib.request.Request(f"https://api.stocktwits.com/api/2/streams/symbol/{t}.json", headers={"User-Agent": UA})
    d = _j.load(urllib.request.urlopen(req, timeout=15))
    msgs = d.get("messages", [])
    tags = [((m.get("entities") or {}).get("sentiment") or {}).get("basic") for m in msgs]
    return {"messages": len(msgs), "bullish": tags.count("Bullish"), "bearish": tags.count("Bearish"),
            "latest": [_clean(m.get("body"), 140) for m in msgs[:5]]}
