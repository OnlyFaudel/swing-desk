"""Nuclear red team: every week, replay the real shocks that hit nuclear and uranium stocks on what we hold right now,
so the team sees how much each one would cost us today. The account is nuclear by design, so the question isn't
'are we diversified' but 'which nuclear-specific blowup hurts us most, and what would tell us it's starting'.
"""
import datetime as dt

SCENARIOS = {
    "Fukushima accident (Mar 2011)": ("2011-03-10", "2011-03-16", "a reactor accident: public fear, plant shutdowns, uranium demand doubts"),
    "COVID crash (Feb-Mar 2020)": ("2020-02-20", "2020-03-18", "a market-wide crash: everything sold, panic days back to back"),
    "Kazakhstan unrest (Jan 2022)": ("2022-01-04", "2022-01-07", "trouble in the biggest uranium producer: spot spikes, but miners swing hard both ways"),
    "Rate shock (Apr-Jun 2022)": ("2022-04-20", "2022-06-16", "rising rates crush growth and speculative names; developers fall most"),
    "Uranium price slide (Feb-Aug 2024)": ("2024-02-05", "2024-08-07", "spot uranium falls ~25% from its high: miners and developers bleed for months"),
    "Yen carry unwind (Aug 2024)": ("2024-07-31", "2024-08-05", "a fast global de-risking: high-momentum names dumped in days"),
    "DeepSeek AI power scare (Jan 2025)": ("2025-01-24", "2025-01-27", "a cheaper-AI shock: data-center power stories (CEG, VST, TLN) collapse in a day"),
}


def stress(book, prices, start_capital):
    """What each historical shock would do to the positions we hold right now (stocks that didn't exist then are skipped)."""
    import yfinance as yf
    pos = {}
    for t, lots in (book.get("lots") or {}).items():
        v = sum(l.get("qty", 0) for l in lots.values()) * prices.get(t, 0)
        if v > 1:
            pos[t] = round(v, 2)
    if not pos:
        return {"positions": {}, "scenarios": []}
    px = yf.download(list(pos), start="2011-01-01", auto_adjust=True, progress=False)["Close"]
    if hasattr(px, "to_frame") and not hasattr(px, "columns"):
        px = px.to_frame(list(pos)[0])
    out = []
    for name, (a, b, why) in SCENARIOS.items():
        hit, missing = 0.0, []
        for t, v in pos.items():
            s = px[t].dropna() if t in px else None
            if s is None or s.empty or s.index[0] > dt.datetime.fromisoformat(a) - dt.timedelta(days=5):
                missing.append(t); continue
            p0 = s[s.index <= a].iloc[-1]; p1 = s[s.index <= b].iloc[-1]
            hit += v * (p1 / p0 - 1)
        out.append({"scenario": name, "what_it_was": why, "dollars": round(hit, 2), "pct_of_account": round(hit / start_capital * 100, 1),
                    "not_listed_then": missing})
    out.sort(key=lambda x: x["dollars"])
    return {"positions": pos, "scenarios": out}
