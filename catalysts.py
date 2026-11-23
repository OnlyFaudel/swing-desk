"""Catalyst calendar: the dated events that move our stocks, in one list for the team and the page.

Sources: each company's next earnings date, and every reminder the team has written (DOE awards, NRC decisions, PJM
auctions, votes, contract deadlines...). Tested 2010-2026 on 442 earnings: the reaction day moves 4.5% on average either
way and there is no reliable drift afterwards (big up reactions faded -1.6% vs the group over 5 days, but the halves
disagree), so the bot steps aside before earnings instead of betting on them.
"""
import datetime as dt
import market, desk_memory


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
    seen, uniq = set(), []
    for x in sorted(out, key=lambda x: x["date"]):
        k = (x["date"], x["what"][:60])
        if k not in seen:
            seen.add(k); uniq.append(x)
    return uniq
