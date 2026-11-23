"""Stock files: one organized file per stock (and one for the whole sector) that the bot rebuilds from everything it
collects, for the owner to read on the page and for the agents to use as "everything we know about this stock".

Sections (same order in every file):
  1 Snapshot            price, moves, distance from highs, trend, volatility, where the volume sits
  2 Business            what the company does and the places it depends on
  3 Places and operations   local news by mine/plant/reactor/country this week, reactor status for owners
  4 News                latest headlines from every source, tagged
  5 Filings and company events   SEC filings and corporate events with what the stock did after each
  6 Government and laws  regulation, policy, politics touching this stock or its places
  7 Workers and jobs    hiring, layoffs, strikes, unions
  8 Crowd               StockTwits mood and latest posts (Reddit when keys are added)
  9 Options and big money   put/call walls, skew, short interest signals
 10 What history says   for each kind of event, what this stock did next (from desk memory)
 11 Price behavior      its big days and swings since 2019 and what followed; panic-day record
 12 Discoveries         patterns the discovery engine found that apply to this stock
 13 Our trades          live and practice (shadow) trades, current setup status
 14 Team notes          what the agents said about it, the owner's posts and reminders
Files: memory/dossiers/<TICKER>.json  and a copy in docs/dossiers/ for the page.
"""
import datetime as dt, json, os, statistics, time

import numpy as np

import collector, desk_memory, jobs, world, uprice, congress

ROOT = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(ROOT, "memory", "dossiers")
PUB = os.path.join(ROOT, "docs", "dossiers")

PROFILE = {
    "CCJ": ("Cameco", "One of the world's largest uranium producers. Mines in northern Saskatchewan (McArthur River with the Key Lake mill, "
            "Cigar Lake), refining and conversion in Ontario (Blind River, Port Hope), a share of the Inkai mine in Kazakhstan with "
            "Kazatomprom, and 49% of Westinghouse (reactors and fuel). Sells mostly on long-term contracts."),
    "NXE": ("NexGen Energy", "Developer of the Rook I project and its Arrow deposit in Saskatchewan's Athabasca Basin, one of the largest "
            "high-grade uranium deposits not yet in production. Moves on permits, financing and the uranium price."),
    "UEC": ("Uranium Energy Corp", "US uranium miner using in-situ recovery in South Texas (Palangana, Burke Hollow, Goliad) and Wyoming "
            "(Christensen Ranch, Irigaray), plus Canadian projects and a physical uranium inventory. Unhedged: tied to the spot price."),
    "DNN": ("Denison Mines", "Developer of Wheeler River (the Phoenix in-situ project) in Saskatchewan and partner in the McClean Lake mill. "
            "Moves on permits, the build decision and the uranium price."),
    "UUUU": ("Energy Fuels", "Owns the White Mesa Mill in Utah, the only working conventional uranium mill in the US, and mines such as "
             "Pinyon Plain. Also processes rare earths and has heavy-mineral sands projects (Donald, Toliara)."),
    "LEU": ("Centrus Energy", "Supplies enriched uranium to utilities and runs the HALEU enrichment cascade in Piketon, Ohio for the "
            "Energy Department. Exposed to the US ban on Russian enriched uranium and to advanced-reactor demand for HALEU."),
    "BWXT": ("BWX Technologies", "Builds the nuclear reactors and fuel for US Navy submarines and carriers (Lynchburg, Virginia; Nuclear Fuel "
             "Services in Erwin, Tennessee), plus commercial nuclear components in Canada and medical isotopes. Steady government revenue."),
    "CEG": ("Constellation Energy", "Largest US nuclear plant operator (about 25 units in Illinois, Pennsylvania, New York, Maryland and "
            "more), restarting the Crane plant (Three Mile Island 1) for Microsoft. Earns more when power prices and capacity auctions rise."),
    "VST": ("Vistra", "Texas-based power company: Comanche Peak plus the Beaver Valley, Davis-Besse and Perry nuclear plants, gas plants and "
            "retail power. Driven by ERCOT and PJM power prices and data-center deals."),
    "TLN": ("Talen Energy", "Owns the Susquehanna nuclear plant in Pennsylvania, with a power deal for an Amazon data-center campus next "
            "to it. Driven by PJM capacity prices and data-center contracts."),
}
SECTIONS = ["Snapshot", "Business", "Places and operations", "News", "Filings and company events", "Government and laws",
            "Workers and jobs", "Crowd", "Options and big money", "What history says", "Price behavior", "Discoveries",
            "Our trades", "Team notes"]


def _load(p, d):
    try:
        return json.load(open(p))
    except Exception:
        return d


def _csv(name):
    try:
        import pandas as pd
        return pd.read_csv(os.path.join(ROOT, "research", name))
    except Exception:
        return None


def _snapshot(t, st, data):
    out = {"price": (st.get("last_prices") or {}).get(t)}
    df = (data or {}).get(t)
    if df is not None and len(df) > 60:
        c = df.Close.dropna()
        p = float(c.iloc[-1]); out["price"] = round(p, 2)
        for k, n in (("day_pct", 1), ("week_pct", 5), ("month_pct", 21), ("quarter_pct", 63)):
            if len(c) > n:
                out[k] = round((p / float(c.iloc[-1 - n]) - 1) * 100, 2)
        out["under_20d_high_pct"] = round((p / float(c.iloc[-20:].max()) - 1) * 100, 1)
        out["under_1y_high_pct"] = round((p / float(c.iloc[-252:].max()) - 1) * 100, 1)
        out["vs_50d_avg_pct"] = round((p / float(c.iloc[-50:].mean()) - 1) * 100, 1)
        if len(c) >= 200:
            out["vs_200d_avg_pct"] = round((p / float(c.iloc[-200:].mean()) - 1) * 100, 1)
        out["daily_move_typical_pct"] = round(float(c.pct_change().iloc[-60:].std() * 100), 2)
    sync = (st.get("sync") or {}).get("partners_pct", {})
    if t in sync:
        out["vs_own_average_pct"] = sync[t]
    return out


def _items(t=None, days=30, tags=None, places=None):
    cut = time.time() - days * 86400
    out = []
    for i in _load(collector.ITEMS, []):
        if i["ts"] < cut or i.get("echo_of"):
            continue
        if t and t not in i.get("tickers", []) and not (places and i.get("place") in places):
            continue
        if tags and not set(tags) & set(i.get("tags", [])):
            continue
        out.append({k: i.get(k) for k in ("date", "title", "outlet", "place", "tags", "numbers", "link", "score")})
    return sorted(out, key=lambda x: (x["date"], x.get("score") or 0), reverse=True)


def build_one(t, st, data=None):
    places = [p for p, v in collector.PLACES.items() if t in v[1]]
    d = {"ticker": t, "name": PROFILE.get(t, (t, ""))[0], "built": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "sections": {}}
    S = d["sections"]
    S["Snapshot"] = _snapshot(t, st, data)
    vp = ((st.get("candidates") or {}).get(t) or {}).get("volume")
    if vp:
        S["Snapshot"]["volume_profile"] = vp
    S["Business"] = {"what_it_does": PROFILE.get(t, ("", "Not profiled yet."))[1], "places_it_depends_on": places}
    week = {p: n for p, n in ((st.get("intel_view") or {}).get("places") or {}).items() if p in places}
    po = {"stories_this_week_by_place": week, "latest_local": _items(t, 14, places=places)[:12]}
    rs = _load(os.path.join(ROOT, "memory", "intel", "reactor_status.json"), {})
    if t in (rs.get("owners") or {}):
        po["reactors"] = {**rs["owners"][t], "report_date": rs.get("date"),
                          "open_outages": [o for o in rs.get("open_outages", []) if o.get("owner") == t]}
    S["Places and operations"] = po
    nf = [{"date": (f.get("ts") and dt.datetime.fromtimestamp(f["ts"]).strftime("%Y-%m-%d")) or f.get("date"), "title": f.get("title"),
           "source": f.get("source"), "link": f.get("link")} for f in (st.get("news_feed") or []) if f.get("ticker") == t][-25:]
    S["News"] = {"headlines": list(reversed(nf)), "local_and_official": _items(t, 30)[:20]}
    ev = [e for e in desk_memory.events() if e["ticker"] == t]
    S["Filings and company events"] = {"count_since_2019": len(ev), "latest": [
        {k: e.get(k) for k in ("date", "type", "title", "source", "r0", "r5", "r20", "x20")} for e in sorted(ev, key=lambda e: e["date"])[-30:][::-1]]}
    gov = _items(t, 60, tags=["regulation", "politics"], places=places) + [
        i for i in _items(None, 60, tags=["regulation", "politics"]) if i.get("place") in ("US policy", "Russia supply", "Kazakhstan", "Niger")]
    seen, gl = set(), []
    for i in gov:
        if i["title"] not in seen:
            seen.add(i["title"]); gl.append(i)
    S["Government and laws"] = {"latest": gl[:20]}
    js = jobs.summary(ticker=t)
    S["Workers and jobs"] = {"news": _items(t, 90, tags=["jobs"])[:15],
                             "own_job_board": {"open_jobs": (js.get("open_jobs_by_company") or {}).get("Constellation")} if t == "CEG" and js else None,
                             "sector_hiring": {k: js.get(k) for k in ("as_of", "sector_open_jobs", "change_vs_30_days_ago", "open_jobs_by_company", "new_postings_30d_by_theme")} if js else None,
                             "new_postings": (js.get("latest_new_postings") or [])[:8]}
    tw = (st.get("stocktwits") or {}).get(t) or {}
    S["Crowd"] = {"stocktwits": {k: tw.get(k) for k in ("messages", "bullish", "bearish")}, "latest_posts": (tw.get("latest") or [])[:10]}
    br = ((st.get("brief") or {}).get("tickers") or {}).get(t) or {}
    ih = st.get("intel_history") or {}
    last = ih[max(ih)].get(t) if ih else None
    S["Options and big money"] = {"options": br.get("options"), "latest_signals": last,
                                  "history_days": [{"date": k, **(v.get(t) or {})} for k, v in sorted(ih.items())[-10:]]}
    S["What history says"] = {ty: desk_memory.playbook(ty, [t]) for ty in sorted({e["type"] for e in ev})}
    pb = {}
    bm = _csv("big_moves.csv")
    if bm is not None:
        g = bm[bm.ticker == t]
        if len(g):
            pb["big_days_since_2019"] = int(len(g))
            for cat in ("company", "sector", "market"):
                for dirn, m in (("up", g.ret > 0), ("down", g.ret < 0)):
                    x = g[(g.cat == cat) & m]
                    if len(x) >= 5:
                        pb[f"{cat}-only {dirn} days (n={len(x)}): next 5 days vs basket"] = f"{x.a5.mean():+.2f}%"
            pb["latest_big_days"] = g.sort_values("date").tail(8)[["date", "ret", "cat", "a5"]].to_dict("records")[::-1]
    sw = _csv("swings_up.csv")
    if sw is not None:
        x = sw[sw.ticker == t]
        if len(x):
            pb["up_swings_since_2019"] = {"count": int(len(x)), "median_size_pct": round(float(x.swing.median()), 1),
                                          "median_days": float(x.days.median()), "latest": x.tail(5)[["low_date", "low", "swing", "days"]].to_dict("records")[::-1]}
    pr = [e for e in st.get("panic_log", []) if e["ticker"] == t]
    if pr:
        pb["panic_day_record"] = pr[-10:]
    S["Price behavior"] = pb
    disc = _load(os.path.join(ROOT, "research", "discoveries.json"), {})
    grp = [g for g, tks in {"miners": ["CCJ", "NXE", "UEC", "DNN", "UUUU"], "fuel and tech": ["LEU", "BWXT"], "power": ["CEG", "VST", "TLN"]}.items() if t in tks]
    rel = lambda s: "(all our stocks)" in s["event"] or any(f"({g})" in s["event"] for g in grp) or "whole basket" in s["event"]
    S["Discoveries"] = {"holding_up": [s for s in disc.get("survivors", []) if rel(s)][:10],
                        "closest_misses": [s for s in disc.get("closest_misses", []) if rel(s)][:6]}
    sh = [x for x in (st.get("shadow_desk") or {}).get("trades", []) if x.get("tk") == t]
    R = [x["R"] for x in sh]
    S["Our trades"] = {"setup_status": (st.get("setup_status") or {}).get(t), "no_new_buys_until": (st.get("avoid") or {}).get(t),
                       "favored_until": (st.get("favor") or {}).get(t),
                       "discovery_actions": [a for a in st.get("auto_log", []) if t in a.get("targets", [])][-8:],
                       "open": (st.get("book") or {}).get("lots", {}).get(t),
                       "closed": [x for x in (st.get("book") or {}).get("trades", []) if x.get("ticker") == t][-10:],
                       "practice_trades": {"n": len(R), "avg_R": round(statistics.mean(R), 3) if R else None,
                                           "win_rate": round(float(np.mean([r > 0 for r in R])), 2) if R else None}}
    posts = [{"t": p.get("t"), "who": p.get("who"), "text": p.get("text", "")[:300]} for p in (st.get("feed") or []) if t in (p.get("tickers") or [])][-12:]
    chats = [{"t": m.get("t"), "who": m.get("who"), "text": m.get("text", "")[:300]} for c in (st.get("chats") or []) if t in (c.get("tickers") or [])
             for m in c.get("msgs", []) if m.get("who") not in ("system",)][-15:]
    S["Team notes"] = {"posts": posts[::-1], "chat": chats[::-1],
                       "owner_posts": [o for o in st.get("owner_posts", []) if t.lower() in o.get("text", "").lower()][-5:],
                       "reminders": [w for w in desk_memory.watch_all() if w.get("ticker") == t][-10:],
                       "desk_decisions": [{k: x.get(k) for k in ("date", "trigger", "headline")} for x in st.get("desk_log", []) if x.get("ticker") == t][-8:]}
    return d


MARKET = {"SRUUF": "Sprott Physical Uranium Trust (follows the uranium spot price)", "URA": "Global X Uranium ETF",
          "URNM": "Sprott Uranium Miners ETF", "NLR": "VanEck Uranium and Nuclear ETF", "^VIX": "VIX fear gauge", "SPY": "S&P 500"}


def _market(st):
    """Daily refresh (cached): how the uranium market and the broad market are moving."""
    c = st.get("sector_prices") or {}
    if c and time.time() - c.get("_at", 0) < 6 * 3600:
        return c
    try:
        import yfinance as yf
        px = yf.download(list(MARKET), period="1y", auto_adjust=True, progress=False)["Close"]
        out = {"_at": time.time()}
        for t, name in MARKET.items():
            s = px[t].dropna()
            if len(s) < 30:
                continue
            p = float(s.iloc[-1])
            out[name] = {"last": round(p, 2), "day_pct": round((p / float(s.iloc[-2]) - 1) * 100, 2),
                         "week_pct": round((p / float(s.iloc[-6]) - 1) * 100, 2), "month_pct": round((p / float(s.iloc[-22]) - 1) * 100, 2),
                         "year_pct": round((p / float(s.iloc[0]) - 1) * 100, 1), "under_1y_high_pct": round((p / float(s.max()) - 1) * 100, 1)}
        st["sector_prices"] = out
        return out
    except Exception as e:
        print("sector prices failed", e)
        return c


def build_sector(st):
    rs = _load(os.path.join(ROOT, "memory", "intel", "reactor_status.json"), {})
    by_place = {}
    for i in _items(None, 30):
        by_place.setdefault(i["place"], []).append(i)
    disc = _load(os.path.join(ROOT, "research", "discoveries.json"), {})
    return {"ticker": "SECTOR", "name": "The nuclear sector", "built": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "sections": {
        "Uranium market": {"uranium_price_per_lb": uprice.summary(), "funds_and_markets": {k: v for k, v in _market(st).items() if k != "_at"},
                           "latest": (by_place.get("Uranium price", []) + by_place.get("Sprott trust", []))[:15]},
        "Government and laws": {"bills_in_congress": congress.summary(), "latest": [i for i in _items(None, 60, tags=["regulation", "politics"])][:25]},
        "Countries": {"who_runs_builds_and_needs_uranium": world.summary(),
                      "latest_by_country": {p: by_place.get(p, [])[:5] for p in ("China new builds", "India", "Japan restarts", "South Korea", "Europe new builds",
                                                                                "France and UK", "Middle East", "Asia newcomers", "Canada SMRs")}},
        "Supply countries": {p: by_place.get(p, [])[:6] for p in ("Kazakhstan", "Niger", "Namibia", "Russia supply")},
        "Defense and geopolitics": {p: by_place.get(p, [])[:6] for p in ("Iran", "North Korea", "War zones", "AUKUS and navies", "Weapons programs", "Stockpiles and reserves")},
        "Big tech power deals": (by_place.get("Big tech power deals", []) + by_place.get("Data-center nuclear deals", []))[:12],
        "Workers and jobs": jobs.summary(),
        "Reactors and power": {"us_fleet_running_pct": rs.get("us_fleet_running_pct"), "report_date": rs.get("date"),
                               "owners": rs.get("owners"), "open_outages": rs.get("open_outages"),
                               "grid_news": (by_place.get("PJM grid", []) + by_place.get("ERCOT grid", []) + by_place.get("Data-center nuclear deals", []))[:12]},
        "New builds and restarts": {p: by_place.get(p, [])[:6] for p in ("Japan restarts", "China new builds", "Crane / Three Mile Island", "Westinghouse", "HALEU")},
        "Discoveries": {"holding_up": disc.get("survivors", [])[:12], "closest_misses": disc.get("closest_misses", [])[:8],
                        "tests_ever": disc.get("tests_ever"), "events_tested": disc.get("events")},
        "Rules the bot follows from its discoveries": {"active_patterns": disc.get("survivors", []), "no_new_buys": st.get("avoid", {}), "favored": st.get("favor", {}),
                                                       "recent_actions": st.get("auto_log", [])[-15:],
                                                       "how": "A pattern must hold in the older AND newer half of the history after correcting for the number of tests. "
                                                              "Up-patterns buy near the close of the news day (10% each, 3 at most) and sell after the pattern's horizon; "
                                                              "down-patterns pause support-level buys in that stock."},
        "Research log": st.get("research_log", []),
        "Panic-day record": st.get("panic_log", [])[-20:]}}


def build_all(st, data=None, tickers=None):
    os.makedirs(DIR, exist_ok=True); os.makedirs(PUB, exist_ok=True)
    idx = []
    for t in list(tickers or st.get("active") or []) + ["SECTOR"]:
        try:
            d = build_sector(st) if t == "SECTOR" else build_one(t, st, data)
        except Exception as e:
            print("dossier failed", t, e); continue
        s = json.dumps(d, default=str, separators=(",", ":"))
        for p in (os.path.join(DIR, f"{t}.json"), os.path.join(PUB, f"{t}.json")):
            open(p, "w").write(s)
        snap = d["sections"].get("Snapshot", {})
        idx.append({"ticker": t, "name": d["name"], "price": snap.get("price"), "week_pct": snap.get("week_pct"), "built": d["built"]})
    st["dossier_index"] = idx
    return idx


def for_agent(t, k=6):
    """A compact 'everything we know' for an agent prompt (keeps token cost small)."""
    d = _load(os.path.join(DIR, f"{t}.json"), {})
    S = d.get("sections", {})
    if not S:
        return None
    up = uprice.summary()
    return {"business": S.get("Business", {}).get("what_it_does"), "snapshot": S.get("Snapshot"),
            "uranium_price": {k: {"usd_per_lb": v.get("usd_per_lb"), "12m_change_pct": v.get("12m_change_pct")} for k, v in up.items() if isinstance(v, dict)},
            "reactors": S.get("Places and operations", {}).get("reactors"),
            "local_news": [i["title"] for i in S.get("Places and operations", {}).get("latest_local", [])[:k]],
            "government": [i["title"] for i in S.get("Government and laws", {}).get("latest", [])[:4]],
            "history": {ty: v for ty, v in list(S.get("What history says", {}).items())[:6]},
            "patterns": {k2: v for k2, v in S.get("Price behavior", {}).items() if "days" in k2 and isinstance(v, str)},
            "discoveries": [f"{s['event']} {s['metric']} {s['avg_pct']:+.2f}%" for s in S.get("Discoveries", {}).get("holding_up", [])[:4]]}
