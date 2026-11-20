"""Research Lab: the agents do research in the background, and code keeps them honest.

Each session (weekday evenings + Saturday):
  1. The Research Lead reads the notebook and proposes up to 2 ideas, written as a test the code can run on the
     Shadow Desk's practice trades ("trades taken when the stock fell 5%+ in the prior week do better").
  2. Code tests each idea: the matching trades vs all the others, in the older half AND the newer half of the record.
  3. The Risk Manager argues why the result could be luck; the Research Lead answers and writes the note.
  4. Notes go in the notebook (Team chat + page). Ideas that hold up in both halves become candidates; they are shown
     to the team in later meetings but NEVER change trading on their own. Every idea tested raises the trial count.
"""
import datetime as dt, json, math, os
import numpy as np, pandas as pd
import feed

ROOT = os.path.dirname(os.path.abspath(__file__))

FEATURES = {
    "group": "sector group of the stock (uranium/nuclear, scarce materials, AI chips, AI power, high beta, megacap)",
    "tk": "ticker",
    "weekday": "day the buy filled: Mon Tue Wed Thu Fri",
    "hour": "hour the buy filled, 9-15 (Eastern)",
    "open_fill": "true if the buy filled in the first hour (often a gap down into the level)",
    "ret5d_pct": "stock's % move over the ~5 trading days before the buy",
    "dist_avg_pct": "% the price sat above (+) or below (-) its 10-day average at the buy",
    "vol_pct": "typical hourly range as % of price (how jumpy the stock was)",
    "group_up": "true if the stock's sector group was above its 10-day average at the buy",
}
OPS = {"<": lambda s, v: s < v, ">": lambda s, v: s > v, "==": lambda s, v: s == v}


# ------------------------------------------------------------------ test an idea on the practice trades
def test(trades, h, min_n=25):
    df = pd.DataFrame(trades)
    f = h.get("feature")
    if f not in FEATURES or f not in df.columns or h.get("op") not in OPS:
        return {"verdict": "invalid", "why": f"can't test feature {f!r} / op {h.get('op')!r}"}
    v = h.get("value")
    col = df[f]
    try:
        if col.dtype == bool or f in ("open_fill", "group_up"):
            v = str(v).lower() in ("true", "1", "yes"); col = col.astype(bool)
        elif col.dtype.kind in "if":
            v = float(v)
        m = OPS[h["op"]](col, v)
    except Exception as e:
        return {"verdict": "invalid", "why": str(e)[:100]}
    df = df.assign(_m=m.fillna(False)).sort_values("entry")
    half = df.entry.iloc[len(df) // 2]
    out = {"n_match": int(df._m.sum()), "n_total": int(len(df))}
    for name, part in (("older", df[df.entry < half]), ("newer", df[df.entry >= half])):
        a, b = part[part._m].R, part[~part._m].R
        out[name] = {"n": int(len(a)), "avgR_match": round(float(a.mean()), 3) if len(a) else None,
                     "avgR_rest": round(float(b.mean()), 3) if len(b) else None,
                     "diff": round(float(a.mean() - b.mean()), 3) if len(a) and len(b) else None}
    a, b = df[df._m].R, df[~df._m].R
    if len(a) >= 2 and len(b) >= 2:
        se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
        tstat = (a.mean() - b.mean()) / se if se > 0 else 0.0
        out["t"] = round(float(tstat), 2)
        out["p"] = round(float(math.erfc(abs(tstat) / math.sqrt(2))), 4)
    o, n = out["older"], out["newer"]
    claim = 1 if h.get("claim", "better") == "better" else -1
    if min(o["n"], n["n"]) < min_n:
        out["verdict"] = "not enough data"
    elif o["diff"] is not None and n["diff"] is not None and np.sign(o["diff"]) == np.sign(n["diff"]) == claim \
            and min(abs(o["diff"]), abs(n["diff"])) >= 0.1 and out.get("p", 1) < 0.05:
        out["verdict"] = "promising"
    elif o["diff"] is not None and n["diff"] is not None and np.sign(o["diff"]) != np.sign(n["diff"]):
        out["verdict"] = "flipped between halves (likely luck)"
    else:
        out["verdict"] = "not supported"
    return out


def _key(h):
    return f"{h.get('feature')} {h.get('op')} {h.get('value')}"


def _trial(n=1):
    p = os.path.join(ROOT, "research", "trial_ledger.json")
    try:
        L = json.load(open(p))
        fam = L["strategies"].setdefault("shadow_patterns", {"trials": 0, "verdict": "background research lab"})
        fam["trials"] += n
        json.dump(L, open(p, "w"), indent=1)
        return fam["trials"]
    except Exception:
        return None


# ------------------------------------------------------------------ one session
def session(st, desk, max_ideas=2):
    trades = (st.get("shadow_desk") or {}).get("trades", [])
    with_feats = [t for t in trades if "ret5d_pct" in t]
    nb = st.setdefault("notebook", [])
    if len(with_feats) < 120:
        feed.post("researcher", f"Research paused: {len(with_feats)} practice trades with full details so far; tests need 120+. "
                  "The Shadow Desk adds more every evening.", kind="learn")
        return []
    tested = {n["key"] for n in nb if n.get("key")}
    summary = {"n_trades": len(with_feats), "avgR": round(float(np.mean([t["R"] for t in with_feats])), 3),
               "by_group": pd.DataFrame(with_feats).groupby("group").R.agg(["count", "mean"]).round(3).to_dict(),
               "features": FEATURES, "already_tested": sorted(tested)[-60:],
               "recent_notes": [{k: n.get(k) for k in ("key", "verdict", "note", "next")} for n in nb[-12:]],
               "learn_report": st.get("learn_report")}
    results = []
    with feed.thread(f"Research session {dt.date.today():%a %b %d}", [], kind="research"):
        feed.say("chief", f"Research time. {len(with_feats):,} practice trades on file, average {summary['avgR']:+.3f}R. "
                 "Research Lead, what should we test? Ideas must be checkable on the practice trades.", to="researcher")
        prop = desk.ask("researcher", "fast",
                        "Research Lead. Propose up to 2 NEW ideas that might make Patient Levels trades better or worse, each a "
                        "test on one feature of the practice trades. Use only the listed features and ops (<, >, ==). Don't "
                        "repeat anything in already_tested. Prefer ideas with an economic reason (a sector selloff breaks "
                        "supports; a jumpy stock blows through tight stops). "
                        '{"say":"","to":"Risk Manager","ideas":[{"feature":"","op":"<|>|==","value":"","claim":"better|worse","why":""}]}',
                        summary, max_tokens=700)
        ideas = [i for i in (prop.get("ideas") or []) if isinstance(i, dict) and _key(i) not in tested][:max_ideas]
        if not ideas:
            feed.say("chief", "No new testable idea this time.")
            return []
        for h in ideas:
            r = test(with_feats, h)
            r["trial_no"] = _trial() if r["verdict"] != "invalid" else None
            o, n = r.get("older", {}), r.get("newer", {})
            feed.say("shadow", f"Test: trades where {_key(h)} ({r.get('n_match', 0)} of {r.get('n_total', 0)}). "
                     + (f"Older half: {o.get('avgR_match')}R vs {o.get('avgR_rest')}R for the rest. "
                        f"Newer half: {n.get('avgR_match')}R vs {n.get('avgR_rest')}R. p={r.get('p')}. " if o else "")
                     + f"Verdict: {r['verdict']}.", to="researcher")
            results.append((h, r))
        crit = desk.ask("risk", "fast",
                        "Risk Manager reviewing the research results. Say plainly whether each could be luck: small samples, "
                        "the number of ideas tested so far, halves that disagree, or a story invented after seeing the data. "
                        '{"say":"","to":"Research Lead"}', {"results": [{"idea": h, "result": r} for h, r in results],
                                                            "ideas_tested_so_far": len(tested) + len(results)}, max_tokens=400)
        note = desk.ask("researcher", "fast",
                        "Research Lead. Answer the Risk Manager, then write the notebook entry: one plain-English note per "
                        "idea (what we tested, what we found, what it means for trading, if anything) and what to test next. "
                        '{"say":"","to":"Risk Manager","notes":[{"key":"feature op value","note":"","next":""}]}',
                        {"results": [{"idea": h, "result": r} for h, r in results], "critique": crit.get("say")}, max_tokens=700)
        notes = {n.get("key"): n for n in (note.get("notes") or []) if isinstance(n, dict)}
        for h, r in results:
            k = _key(h); nn = notes.get(k) or {}
            nb.append({"t": feed._now().strftime("%Y-%m-%d %H:%M"), "key": k, "idea": h, "result": r, "verdict": r["verdict"],
                       "note": nn.get("note") or h.get("why", ""), "next": nn.get("next", "")})
    del nb[:-300]
    for h, r in results:
        good = r["verdict"] == "promising"
        feed.post("researcher", f"Tested: {_key(h)} ({h.get('claim')}). Verdict: {r['verdict']}. "
                  + (notes.get(_key(h), {}).get("note") or ""), kind="learn",
                  art={"big": ("Promising: " if good else "Tested: ") + _key(h), "sub": r["verdict"].capitalize()
                       + (". Watching it, not trading on it." if good else "")})
        if good:
            st.setdefault("research_candidates", []).append({"key": _key(h), "idea": h, "result": r, "found": str(dt.date.today())})
    return results


def highlights(st, n=5):
    """What the team should keep in mind (fed into the morning meeting and level decisions)."""
    nb = st.get("notebook", [])
    keep = [x for x in nb if x.get("verdict") == "promising"][-n:]
    return [{"finding": x["key"], "claim": x["idea"].get("claim"), "note": x.get("note"), "status": "candidate: not proven, don't over-weight"}
            for x in keep]
