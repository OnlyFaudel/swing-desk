"""Discovery engine: every night the bot tests what each kind of event did to our stocks, on everything it has collected
(SEC filings, local intel, reactor outages, news bursts, years of archived news, government and law headlines).

The rules that keep it honest (so a lucky pattern can't sneak in):
  * an effect counts only if it shows up in the OLDER half of the history AND again in the NEWER half, same direction;
  * every test run is counted, and the whole night's batch is corrected for how many were tried (Benjamini-Hochberg);
  * outcomes are measured AFTER the first day (the part we could still trade), against the basket for single stocks.
Survivors are posted by the Research Lead, saved in research/discoveries.json, and handed to the agents as context.
"""
import datetime as dt, json, os

import numpy as np
from scipy import stats

import desk_memory

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "research", "discoveries.json")
ARCHIVE = os.path.join(ROOT, "memory", "archive_events.json")
PRICE = os.path.join(ROOT, "memory", "price_events.json")
HISTORY = os.path.join(ROOT, "memory", "history_events.json")
PEOPLE = os.path.join(ROOT, "memory", "people_events.json")
GROUPS = {"miners": ["CCJ", "NXE", "UEC", "DNN", "UUUU"], "fuel and tech": ["LEU", "BWXT"], "power": ["CEG", "VST", "TLN"]}
PLAIN = {"x1": "vs normal, the next day", "x5": "vs the basket (or its normal trend) over the next 5 days", "x20": "vs the basket (or its normal trend) over the next 20 days",
         "r5": "over the next 5 days", "r20": "over the next 20 days", "r1": "the next day"}


def _load(p, d):
    try:
        return json.load(open(p))
    except Exception:
        return d


def _events():
    ev = desk_memory.events() + _load(ARCHIVE, []) + _load(PRICE, []) + _load(HISTORY, []) + _load(PEOPLE, [])
    one = {}
    for e in ev:  # the same kind of event on the same stock and day counts once
        one.setdefault((e["ticker"], e["date"], e["type"]), e)
    return list(one.values())


def _bh(pvals, q=0.10):
    p = np.asarray(pvals); n = len(p)
    if not n:
        return np.array([], bool)
    order = np.argsort(p); ok = np.zeros(n, bool)
    thresh = q * (np.arange(1, n + 1) / n)
    passed = np.where(p[order] <= thresh)[0]
    if len(passed):
        ok[order[: passed.max() + 1]] = True
    return ok


def run(min_n=30, min_half=10):
    ev = [e for e in _events() if e.get("date")]
    tests = []

    def test(name, rows, metric):
        # news comes in clusters: everything in the same week (same stock) counts as ONE observation
        wk = {}
        for e in rows:
            if e.get(metric) is None:
                continue
            k = (e["ticker"], dt.date.fromisoformat(e["date"]).isocalendar()[:2])
            wk.setdefault(k, []).append((e["date"], e[metric]))
        v = [(min(x[0] for x in xs), sum(x[1] for x in xs) / len(xs)) for xs in wk.values()]
        if len(v) < min_n:
            return
        v.sort()
        mid = v[len(v) // 2][0]
        a = np.array([x for d, x in v if d < mid]); b = np.array([x for d, x in v if d >= mid]); allv = np.array([x for _, x in v])
        if len(a) < min_half or len(b) < min_half:
            return
        t, p = stats.ttest_1samp(allv, 0)
        tests.append({"key": f"{name}|{metric}", "event": name, "metric": metric, "n": len(allv), "avg_pct": round(float(allv.mean()), 2),
                      "up_share": round(float((allv > 0).mean()), 2), "older_avg": round(float(a.mean()), 2), "newer_avg": round(float(b.mean()), 2),
                      "p": float(p), "first": v[0][0], "last": v[-1][0]})

    types = sorted({e["type"] for e in ev})
    for ty in types:
        rows = [e for e in ev if e["type"] == ty]
        stock = [e for e in rows if e["ticker"] != "_basket"]
        basket = [e for e in rows if e["ticker"] == "_basket"]
        for m in ("x5", "x20"):
            test(f"{ty} (all our stocks)", stock, m)
            for g, tks in GROUPS.items():
                test(f"{ty} ({g})", [e for e in stock if e["ticker"] in tks], m)
        for m in ("x1", "x5", "x20"):  # vs the basket's normal trend at the time
            test(f"{ty} (sector/government/peer news, whole basket)", basket, m)

    # the market's verdict on the news: did the first day cheer it or punish it, and did that reaction keep going or reverse?
    for ty in types:
        if ty.startswith(("price_", "macro_")):
            continue
        stock = [e for e in ev if e["type"] == ty and e["ticker"] != "_basket" and e.get("r0") is not None]
        for lab, cond in (("cheered (first day +3% or more)", lambda e: e["r0"] >= 3), ("punished (first day -3% or worse)", lambda e: e["r0"] <= -3)):
            for m in ("x5", "x20"):
                test(f"{ty} {lab} (all our stocks)", [e for e in stock if cond(e)], m)
    ok = _bh([t["p"] for t in tests])
    for t, k in zip(tests, ok):
        t["survives"] = bool(k and np.sign(t["older_avg"]) == np.sign(t["newer_avg"]) == np.sign(t["avg_pct"]) and t["avg_pct"] != 0)
    prev = _load(OUT, {})
    seen = set(prev.get("keys_seen", [])) | {t["key"] for t in tests}
    surv = sorted([t for t in tests if t["survives"]], key=lambda t: t["p"])
    out = {"run_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "events": len(ev), "tests_tonight": len(tests),
           "tests_ever": len(seen), "keys_seen": sorted(seen), "survivors": surv,
           "method": "same-week events count once; single stocks vs the basket, sector news vs the basket's normal trend; older and newer half must agree; Benjamini-Hochberg 10% across the night's tests",
           "closest_misses": sorted([t for t in tests if not t["survives"]], key=lambda t: t["p"])[:15]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    # the research log the agents and the page read
    lp = os.path.join(ROOT, "research", "trial_ledger.json")
    L = _load(lp, {"strategies": {}})
    L.setdefault("strategies", {})["auto_discovery"] = {
        "trials": len(seen),
        "verdict": f"{out['run_at']}: the bot tested {len(tests)} event patterns on {len(ev):,} events (older vs newer half, "
                   f"corrected for the number of tests). {len(surv)} hold up"
                   + (": " + "; ".join(f"{s['event']} -> {s['avg_pct']:+.2f}% {PLAIN.get(s['metric'], s['metric'])} "
                                       f"(n={s['n']}, up {s['up_share']:.0%})" for s in surv[:6]) if surv else ".")}
    json.dump(L, open(lp, "w"), indent=1)
    new = [s for s in surv if s["key"] not in {x["key"] for x in prev.get("survivors", [])}]
    return out, new


def brief(k=8):
    """What the agents get: the patterns that hold up, in plain words."""
    d = _load(OUT, {})
    return [f"{s['event']}: {s['avg_pct']:+.2f}% {PLAIN.get(s['metric'], s['metric'])} (n={s['n']}, older {s['older_avg']:+.2f}, newer {s['newer_avg']:+.2f})"
            for s in d.get("survivors", [])[:k]]


if __name__ == "__main__":
    o, new = run()
    print(o["events"], "events,", o["tests_tonight"], "tests,", len(o["survivors"]), "survive")
    for s in o["survivors"][:15]:
        print(f"  {s['event']:55s} {s['metric']:4s} {s['avg_pct']:+6.2f}% n={s['n']:4d} older {s['older_avg']:+.2f} newer {s['newer_avg']:+.2f} p={s['p']:.4f}")
    print("closest misses:")
    for s in o["closest_misses"][:6]:
        print(f"  {s['event']:55s} {s['metric']:4s} {s['avg_pct']:+6.2f}% n={s['n']:4d} older {s['older_avg']:+.2f} newer {s['newer_avg']:+.2f} p={s['p']:.4f}")
