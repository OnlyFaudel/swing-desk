"""Builds the Control Center (docs/index.html) and the Lab's data file (docs/lab.json)."""
import json, os

ROOT = os.path.dirname(os.path.abspath(__file__))


def build(state, cfg, embed_lab=None, out=None, banner=None):
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
