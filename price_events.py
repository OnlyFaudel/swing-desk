"""Price action as events: what each stock's own trading did (spikes, gaps, new highs/lows, volume surges, losing
streaks, panic days), rebuilt daily from prices since 2019, so the discovery engine tests them with the same strict rules
as the news. memory/price_events.json"""
import json, os

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "memory", "price_events.json")


def build(tickers, start="2018-01-01"):
    import yfinance as yf
    px = yf.download(list(tickers) + ["SPY"], start=start, auto_adjust=True, progress=False)
    C, O, V = px["Close"], px["Open"], px["Volume"]
    R = C.pct_change()
    ev = []
    for t in tickers:
        c, r, o, v = C[t], R[t], O[t], V[t]
        peer = R[[x for x in tickers if x != t]].median(axis=1)
        sig = r.rolling(60).std().shift(1)
        hi52, lo52 = c.rolling(252).max().shift(1), c.rolling(252).min().shift(1)
        gap = o / c.shift(1) - 1
        vr = v / v.rolling(20).mean().shift(1)
        down3 = (r < 0) & (r.shift(1) < 0) & (r.shift(2) < 0)
        rules = {
            "price_spike_up_alone": (r >= 2.5 * sig) & (peer.abs() < sig) & (R.SPY.abs() < 0.01),
            "price_drop_alone": (r <= -2.5 * sig) & (peer.abs() < sig) & (R.SPY.abs() < 0.01),
            "price_sector_selloff": (peer <= -0.04) & (R.SPY > -0.015),
            "price_market_panic": R.SPY <= -0.02,
            "price_new_52w_high": c > hi52,
            "price_new_52w_low": c < lo52,
            "price_gap_down_5": gap <= -0.05,
            "price_gap_up_5": gap >= 0.05,
            "price_volume_3x": vr >= 3,
            "price_3_down_days": down3 & (c / c.shift(3) - 1 <= -0.06),
        }
        for typ, m in rules.items():
            m = m.fillna(False)
            for d in m.index[m.values]:
                if str(d.date()) < "2019-01-01":
                    continue
                ev.append({"ticker": t, "date": str(d.date()), "title": f"{t}: {typ.replace('price_', '').replace('_', ' ')} ({r[d] * 100:+.1f}% that day)",
                           "type": typ, "source": "prices", "r0": None, "r1": None, "r5": None, "r20": None, "r60": None, "x5": None, "x20": None})
    ev += _macro(tickers, start)
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    json.dump(ev, open(PATH, "w"), separators=(",", ":"))
    return len(ev)


MACRO = {"NG=F": ("natural gas", 0.05), "CL=F": ("oil", 0.04), "DX-Y.NYB": ("the dollar", 0.008), "^TNX": ("the 10-year yield", None), "^VIX": ("the VIX fear gauge", None)}


def _macro(tickers, start):
    """The economy's big daily moves, attached to every stock (so the engine can see which group they help or hurt) and
    to the basket: gas sets power prices (CEG/VST/TLN), rates hit builders and miners raising money, the dollar and oil move commodities."""
    import yfinance as yf
    px = yf.download(list(MACRO), start=start, auto_adjust=True, progress=False)["Close"]
    out = []
    for sym, (name, thr) in MACRO.items():
        s = px[sym].dropna()
        if sym == "^TNX":
            ch = s.diff()  # in yield points: 0.10 = 10 basis points
            moves = {"up": ch >= 0.10, "down": ch <= -0.10}
        elif sym == "^VIX":
            ch = s.pct_change()
            moves = {"up": ch >= 0.20, "down": ch <= -0.15}
        else:
            ch = s.pct_change()
            moves = {"up": ch >= thr, "down": ch <= -thr}
        key = name.split()[-1].replace("-", "")
        for way, m in moves.items():
            for d in m.index[m.fillna(False).values]:
                if str(d.date()) < "2019-01-01":
                    continue
                title = f"Big day for {name}: {way} ({ch[d] * (1 if sym == '^TNX' else 100):+.2f}{'' if sym == '^TNX' else '%'})"
                for t in list(tickers) + ["_basket"]:
                    out.append({"ticker": t, "date": str(d.date()), "title": title, "type": f"macro_{key}_{way}", "source": "markets",
                                "r0": None, "r1": None, "r5": None, "r20": None, "r60": None, "x5": None, "x20": None})
    return out


if __name__ == "__main__":
    print(build(["CCJ", "NXE", "UEC", "DNN", "UUUU", "LEU", "BWXT", "CEG", "VST", "TLN"]))


def today(data, tickers):
    """Today's price events from the live daily bars (the bot's own data), with the same rules as build()."""
    import pandas as pd
    if "SPY" not in data:
        return []
    C = pd.DataFrame({t: data[t].Close for t in list(tickers) + ["SPY"] if t in data}).dropna(how="all")
    O = pd.DataFrame({t: data[t].Open for t in tickers if t in data}); V = pd.DataFrame({t: data[t].Volume for t in tickers if t in data})
    R = C.pct_change(); d = C.index[-1]; out = []
    for t in tickers:
        if t not in C or len(C[t].dropna()) < 260:
            continue
        c, r = C[t], R[t]
        peer = R[[x for x in tickers if x != t and x in R]].median(axis=1)
        sig = r.iloc[-61:-1].std()
        flags = {
            "price_spike_up_alone": r[d] >= 2.5 * sig and abs(peer[d]) < sig and abs(R.SPY[d]) < 0.01,
            "price_drop_alone": r[d] <= -2.5 * sig and abs(peer[d]) < sig and abs(R.SPY[d]) < 0.01,
            "price_sector_selloff": peer[d] <= -0.04 and R.SPY[d] > -0.015,
            "price_market_panic": R.SPY[d] <= -0.02,
            "price_new_52w_high": c[d] > c.iloc[-253:-1].max(),
            "price_new_52w_low": c[d] < c.iloc[-253:-1].min(),
            "price_gap_down_5": O[t][d] / c.iloc[-2] - 1 <= -0.05,
            "price_gap_up_5": O[t][d] / c.iloc[-2] - 1 >= 0.05,
            "price_volume_3x": V[t][d] >= 3 * V[t].iloc[-21:-1].mean(),
            "price_3_down_days": (r.iloc[-3:] < 0).all() and c[d] / c.iloc[-4] - 1 <= -0.06,
        }
        out += [{"ticker": t, "date": str(d.date()), "title": f"{t}: {k.replace('price_', '').replace('_', ' ')} ({r[d] * 100:+.1f}% today)", "type": k}
                for k, ok in flags.items() if bool(ok)]
    return out
