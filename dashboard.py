"""Builds the Control Center (docs/index.html) and the Lab's data file (docs/lab.json)."""
import json, os

ROOT = os.path.dirname(os.path.abspath(__file__))


def slim(state):
    """Only what the page shows: the full record (2.5 MB of practice trades, caches, seen-lists) stays in state.json."""
    s = {k: v for k, v in state.items() if k not in ("cache", "seen_news", "intel_handed", "alpaca_seen_fills", "audits", "learning_log",
                                                     "setup_log", "research_candidates", "stocktwits", "intel_history", "event_memory")}
    sh = state.get("shadow_desk") or {}
    s["shadow_desk"] = {"trades": (sh.get("trades") or [])[-50:], "last_run": sh.get("last_run")}
    s["news_feed"] = (state.get("news_feed") or [])[-30:]
    s["desk_log"] = (state.get("desk_log") or [])[-15:]
    s["orders_log"] = (state.get("orders_log") or [])[-60:]
    s["chats"] = (state.get("chats") or [])[-80:]
    s["feed"] = (state.get("feed") or [])[-200:]
    return s


def build(state, cfg, embed_lab=None, out=None, banner=None):
    state = slim(state)
    html = open(os.path.join(ROOT, "web", "app.html")).read()
    engine = open(os.path.join(ROOT, "web", "engine.js")).read()
    html = (html.replace("__ENGINE__", engine)
            .replace("__STATE__", json.dumps(state, default=str).replace("</", "<\\/"))
            .replace("__CFG__", json.dumps(cfg))
            .replace("__LAB__", json.dumps(embed_lab, separators=(",", ":")) if embed_lab else "null")
            .replace("__BANNER__", f'<div class="verdict warn" style="margin:0 0 14px">{banner}</div>' if banner else ""))
    out = out or os.path.join(ROOT, "docs", "index.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write(html)
    return out


def write_lab(hourly, path=None):
    """Compact hourly OHLC for the in-browser Lab (written by the Monday ranking run)."""
    d = {}
    for t, h in hourly.items():
        if h is None or len(h) < 400:
            continue
        r = lambda s: [round(float(v), 2) for v in s]
        d[t] = {"t": [int(x.timestamp()) for x in h.index], "o": r(h.Open), "h": r(h.High), "l": r(h.Low), "c": r(h.Close)}
    path = path or os.path.join(ROOT, "docs", "lab.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(d, open(path, "w"), separators=(",", ":"))
    return d
