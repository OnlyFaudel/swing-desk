"""Catalyst calendar: the dated events that move our stocks, in one list for the team and the page.

Sources: each company's next earnings date, and every reminder the team has written (DOE awards, NRC decisions, PJM
auctions, votes, contract deadlines...). Tested 2010-2026 on 442 earnings: the reaction day moves 4.5% on average either
way and there is no reliable drift afterwards (big up reactions faded -1.6% vs the group over 5 days, but the halves
disagree), so the bot steps aside before earnings instead of betting on them.
"""
import datetime as dt
import market, desk_memory


# Fed decision days (2 pm ET, from federalreserve.gov). Tested 2019-2026, 62 decisions: our 10 stocks rose +0.64% on the
# day vs +0.14% on a normal day (both halves agree, +0.73/+0.56) but that's within noise (t about 1.3), and the 3 days
# before were weaker than normal (halves disagree). Context for the team, not a trading rule.
FOMC = ["2026-12-09", "2027-01-27"]

# Market calendar notes with tested history (research/trial_ledger.json: thanksgiving_week). Context, not rules.
CALENDAR = [
    {"date": "2026-11-25", "what": "Wednesday before Thanksgiving. Since 1996 the S&P rose Fri->Wed of this week 73% of years (+0.69% vs +0.14% "
     "normal); our 10 +1.8% (2008-25, up 67%)."},
    {"date": "2026-11-26", "what": "Thanksgiving: market closed."},
    {"date": "2026-12-15", "what": "PJM 2029/30 capacity auction closes (price floor and cap apply). Matters for TLN, VST, CEG. No FERC ruling found "
                                  "on the new delay request as of Nov 25; assume it goes ahead.", "kind": "macro"},
    {"date": "2026-11-27", "what": "Black Friday: market closes at 1 pm, volume about half of normal. Black Friday close -> Monday has been weak: "
     "S&P up only 40% of 30 years, our 10 -0.5%, power trio -1.7% (down 6 of 7 years since 2019)."},
    {"date": "2026-11-30", "what": "Monday after Thanksgiving. Power trio over the next 2 weeks: -4.1% on average since 2019 (up 2 of 7 years); "
     "miners +1.5% (2008-25). Year-end bounce trades start Dec 18."},
]


def upcoming(tickers, days=45, today=None):
    today = today or dt.date.today()
    end = str(today + dt.timedelta(days=days))
    out = []
    for t in tickers:
        try:
            d = market.next_earnings(t)
        except Exception:
            d = None
        if d and str(today) <= d <= end:
            out.append({"date": d, "ticker": t, "what": f"{t} earnings (moves about 4-5% either way on the day)", "kind": "earnings"})
    for w in desk_memory.watch_all():
        if str(today) <= w["date"] <= end:
            out.append({"date": w["date"], "ticker": w.get("ticker") or "", "what": w["what"], "kind": "reminder", "by": w.get("by")})
    for c in CALENDAR:
        if str(today) <= c["date"] <= end:
            out.append({"date": c["date"], "ticker": "", "kind": "calendar", "what": c["what"]})
    for d in FOMC:
        if str(today) <= d <= end:
            out.append({"date": d, "ticker": "", "kind": "macro",
                        "what": "Fed rate decision, 2 pm. Since 2019 our stocks averaged +0.6% on Fed days vs +0.1% normally (not a sure thing)"})
    seen, uniq = set(), []
    for x in sorted(out, key=lambda x: x["date"]):
        k = (x["date"], x["what"][:60])
        if k not in seen:
            seen.add(k); uniq.append(x)
    return uniq
