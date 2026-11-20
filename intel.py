"""Morning intelligence: everything the desk can legally and freely see about who is positioned where.

  options_positioning  put wall / call wall (biggest open-interest strikes), put/call ratios,
                       unusual options volume, implied move, skew, dealer-gamma estimate
  short_volume         FINRA daily short-sale volume ratio vs its 20-day average
  short_interest       % of float sold short, days to cover (from Yahoo, updated twice a month)
  insiders             SEC Form 4: open-market insider buys/sells in the last 90 days
  crowd                Reddit/WSB mentions (ApeWisdom), analyst consensus and targets
  overnight            markets that trade before the US open: S&P futures, SK Hynix & Samsung (MU),
                       Kazatomprom & uranium funds (CCJ), software ETF (PLTR)
  regime / calendar    S&P vs 200-day avg, VIX + term structure, holidays, half-days, Fed days, opex

NOT visible to anyone outside the broker: other traders' stop-loss orders, hidden (iceberg) orders,
what dark-pool buyers intend. Open interest also doesn't say who bought vs sold.
Every function fails soft (returns {"error": ...}) so one broken source never stops the desk.
"""
import datetime as dt, json, math, re, time, urllib.request
import numpy as np
import pandas as pd
import yfinance as yf

UA = {"User-Agent": "SwingDesk personal research swingdesk.bot@gmail.com"}
PEERS = {"MU": ["000660.KS", "005930.KS", "SMH"], "CCJ": ["KAP.L", "URNM", "SRUUF", "^N225"], "PLTR": ["IGV", "QQQ"],
         "LEU": ["SRUUF", "BWXT", "URNM"], "CEG": ["VST", "TLN", "XLU", "9503.T"],
         "TSM": ["2330.TW", "SMH", "NVDA"], "ETN": ["VRT", "PWR", "XLI"]}


def _get(url, timeout=20, as_json=True):
    req = urllib.request.Request(url, headers=UA)
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    return json.loads(raw) if as_json else raw.decode("utf-8", "ignore")


def soft(fn):
    def w(*a, **k):
        try:
            return fn(*a, **k)
        except Exception as e:
            return {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    w.__name__ = fn.__name__
    return w


# ------------------------------------------------------------------ options
def _bs_gamma(S, K, iv, T):
    if iv <= 0 or T <= 0:
        return 0.0
    d1 = (math.log(S / K) + 0.5 * iv * iv * T) / (iv * math.sqrt(T))
    return math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) / (S * iv * math.sqrt(T))


@soft
def options_positioning(t, spot, max_days=45):
    tk = yf.Ticker(t)
    today = dt.date.today()
    exps = [e for e in tk.options if 0 <= (dt.date.fromisoformat(e) - today).days <= max_days][:6]
    rows = []
    for e in exps:
        ch = tk.option_chain(e)
        T = max((dt.date.fromisoformat(e) - today).days, 0.5) / 365
        for kind, df in (("call", ch.calls), ("put", ch.puts)):
            d = df[["strike", "openInterest", "volume", "impliedVolatility", "bid", "ask", "lastPrice"]].copy()
            d["kind"], d["exp"], d["T"] = kind, e, T
            rows.append(d)
    if not rows:
        return {"error": "no option chain"}
    o = pd.concat(rows).fillna(0)
    o = o[(o.impliedVolatility > 0.05) & (o.impliedVolatility < 3)]
    calls, puts = o[o.kind == "call"], o[o.kind == "put"]
    oi_c = calls.groupby("strike").openInterest.sum()
    oi_p = puts.groupby("strike").openInterest.sum()
    below = oi_p[oi_p.index < spot]
    above = oi_c[oi_c.index > spot]
    put_wall = float(below.idxmax()) if len(below) else None
    call_wall = float(above.idxmax()) if len(above) else None
    # dealer gamma estimate (convention: dealers long calls / short puts -> calls +, puts -)
    o["g"] = [_bs_gamma(spot, k, iv, T) for k, iv, T in zip(o.strike, o.impliedVolatility, o["T"])]
    o["gex"] = o.g * o.openInterest * 100 * spot * spot * 0.01 * np.where(o.kind == "call", 1, -1)
    by_k = o.groupby("strike").gex.sum()
    # nearest expiry with >= 4 days: ATM implied move
    near = [e for e in exps if (dt.date.fromisoformat(e) - today).days >= 4]
    move = atm_iv = skew = None
    if near:
        n = o[o.exp == near[0]]
        k_atm = n.strike.iloc[(n.strike - spot).abs().argsort().iloc[0]]
        atm = n[n.strike == k_atm]
        mid = ((atm.bid + atm.ask) / 2).where(lambda x: x > 0, atm.lastPrice).sum()
        move = round(float(mid / spot * 100), 1)
        atm_iv = round(float(atm.impliedVolatility.mean() * 100), 1)
        otm_put = n[(n.kind == "put") & (n.strike <= spot * 0.92)].sort_values("strike").tail(1)
        if len(otm_put):
            skew = round(float((otm_put.impliedVolatility.iloc[0] - atm.impliedVolatility.mean()) * 100), 1)
    unusual = o[(o.volume >= 500) & (o.volume > 3 * o.openInterest.clip(lower=1))].sort_values("volume", ascending=False).head(4)
    return {
        "put_wall": put_wall, "put_wall_oi": int(below.max()) if len(below) else 0,
        "call_wall": call_wall, "call_wall_oi": int(above.max()) if len(above) else 0,
        "put_call_oi": round(float(puts.openInterest.sum() / max(calls.openInterest.sum(), 1)), 2),
        "put_call_volume": round(float(puts.volume.sum() / max(calls.volume.sum(), 1)), 2),
        "net_dealer_gamma_musd_per_1pct": round(float(o.gex.sum()) / 1e6, 2),
        "biggest_gamma_strike": float(by_k.abs().idxmax()) if len(by_k) else None,
        "implied_move_pct_next_expiry": move, "atm_iv_pct": atm_iv, "put_skew_pts": skew,
        "unusual": [{"type": r.kind, "strike": float(r.strike), "exp": r.exp, "volume": int(r.volume),
                     "open_interest": int(r.openInterest)} for r in unusual.itertuples()],
        "expiries_used": exps,
        "note": ("Open interest is from the previous close and shows where bets sit, not who bought or sold. "
                 "Research: strikes 'pin' price only slightly near expiration; no solid evidence big-OI strikes act as "
                 "multi-day support. Gamma estimate assumes dealers are long calls/short puts, which may be backwards "
                 "in retail-heavy names; treat negative gamma as 'expect bigger swings', not direction. "
                 "Steep put skew has the best evidence (mildly bearish over months)."),
    }


# ------------------------------------------------------------------ short selling
@soft
def short_volume(tickers, cache, days=20):
    """FINRA daily short sale volume (consolidated). Ratio = short volume / total volume."""
    got = cache.setdefault("finra", {})
    d = dt.date.today()
    tries = 0
    while len([k for k in got if k >= str(d - dt.timedelta(days=40))]) < days and tries < 35:
        d -= dt.timedelta(days=1)
        tries += 1
        key = str(d)
        if d.weekday() >= 5 or key in got:
            continue
        try:
            txt = _get(f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{d:%Y%m%d}.txt", as_json=False)
        except Exception:
            got[key] = None
            continue
        row = {}
        for line in txt.splitlines()[1:]:
            p = line.split("|")
            if len(p) >= 5 and p[1] in tickers:
                row[p[1]] = round(float(p[2]) / max(float(p[4]), 1), 3)
        got[key] = row
    for k in sorted(got)[:-60]:
        del got[k]
    out = {}
    for t in tickers:
        s = [(k, v[t]) for k, v in sorted(got.items()) if v and t in v]
        if s:
            vals = [x for _, x in s[-days:]]
            sd = float(np.std(vals[:-1])) if len(vals) > 5 else 0
            z = round((vals[-1] - float(np.mean(vals[:-1]))) / sd, 2) if sd > 0 else None
            out[t] = {"latest": vals[-1], "latest_date": s[-1][0], "avg_20d": round(float(np.mean(vals)), 3), "zscore": z,
                      "note": "FINRA off-exchange short volume only (not short interest; includes market-maker hedging). "
                              "Only unusual readings vs this stock's own history (|z|>2) mean anything, and weakly."}
    return out


@soft
def fundamentals(t):
    i = yf.Ticker(t).info
    pick = ["shortPercentOfFloat", "shortRatio", "beta", "recommendationMean", "recommendationKey",
            "targetMeanPrice", "targetLowPrice", "targetHighPrice", "numberOfAnalystOpinions",
            "heldPercentInstitutions", "heldPercentInsiders", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "marketCap"]
    return {k: i.get(k) for k in pick}


# ------------------------------------------------------------------ insiders (Form 4)
@soft
def insiders(t, cik, cache, days=90):
    sub = _get(f"https://data.sec.gov/submissions/CIK{cik}.json")["filings"]["recent"]
    seen = cache.setdefault("form4", {})
    cutoff = str(dt.date.today() - dt.timedelta(days=days))
    buys = sells = 0.0
    nb = ns = planned = fetched = 0
    who_bought = []
    for i, form in enumerate(sub["form"]):
        if sub["filingDate"][i] < cutoff:
            break
        if form != "4":
            continue
        acc = sub["accessionNumber"][i]
        if acc not in seen:
            if fetched >= 12:
                continue
            fetched += 1
            doc = re.sub(r"^xsl[^/]+/", "", sub["primaryDocument"][i])
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"
            try:
                x = _get(url, as_json=False)
                time.sleep(0.15)
            except Exception:
                continue
            name = (re.search(r"<rptOwnerName>(.*?)</rptOwnerName>", x, re.S) or [None, "?"])[1].strip()
            plan = "<aff10b5One>1" in x or "<aff10b5One>true" in x.lower()
            tx = []
            for blk in re.findall(r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>", x, re.S):
                code = (re.search(r"<transactionCode>(\w)</transactionCode>", blk) or [None, ""])[1]
                sh = re.search(r"<transactionShares>\s*<value>([\d.]+)", blk)
                px = re.search(r"<transactionPricePerShare>\s*<value>([\d.]+)", blk)
                if code in ("P", "S") and sh:
                    tx.append([code, float(sh.group(1)), float(px.group(1)) if px else 0.0])
            seen[acc] = {"name": name, "plan": plan, "tx": tx, "date": sub["filingDate"][i]}
        rec = seen[acc]
        for code, sh, px in rec["tx"]:
            if code == "P":
                buys += sh * px; nb += 1; who_bought.append(rec["name"])
            else:
                sells += sh * px; ns += 1; planned += rec["plan"]
    return {"open_market_buys": nb, "buy_usd": round(buys), "sells": ns, "sell_usd": round(sells),
            "sells_under_10b5_1_plan": planned, "buyers": sorted(set(who_bought))[:5], "window_days": days,
            "note": "Open-market insider BUYS (especially several insiders) are the meaningful signal; planned sales mostly aren't."}


# ------------------------------------------------------------------ crowd
@soft
def reddit(tickers):
    out = {}
    for page in range(1, 6):
        r = _get(f"https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}")
        for x in r.get("results", []):
            if x["ticker"] in tickers:
                out[x["ticker"]] = {"rank": x.get("rank"), "mentions_24h": x.get("mentions"),
                                    "mentions_prev_24h": x.get("mentions_24h_ago"), "upvotes": x.get("upvotes")}
        if len(out) == len(tickers) or page >= r.get("pages", 1):
            break
    return out


# ------------------------------------------------------------------ overnight / regime
@soft
def overnight_and_regime(tickers):
    syms = sorted({p for t in tickers for p in PEERS.get(t, [])} | {"SPY", "ES=F", "^VIX", "^VIX3M", "BTC-USD", "ETH-USD"})
    d = yf.download(syms, period="15mo", auto_adjust=True, progress=False)["Close"]
    out = {"peers": {}}
    for s in syms:
        c = d[s].dropna()
        if len(c) < 3:
            continue
        out["peers"][s] = {"last": round(float(c.iloc[-1]), 2), "date": str(c.index[-1].date()),
                           "chg_pct": round(float(c.iloc[-1] / c.iloc[-2] - 1) * 100, 2),
                           "chg_5d_pct": round(float(c.iloc[-1] / c.iloc[-6] - 1) * 100, 2) if len(c) > 6 else None}
    spy = d["SPY"].dropna()
    sma200 = float(spy.rolling(200).mean().iloc[-1])
    vix = d["^VIX"].dropna(); v3 = d["^VIX3M"].dropna()
    out["regime"] = {"spy": round(float(spy.iloc[-1]), 2), "spy_200d": round(sma200, 2),
                     "market_healthy": bool(spy.iloc[-1] > sma200),
                     "spy_vs_200d_pct": round(float(spy.iloc[-1] / sma200 - 1) * 100, 2),
                     "vix": round(float(vix.iloc[-1]), 2), "vix3m": round(float(v3.iloc[-1]), 2),
                     "vix_backwardation": bool(vix.iloc[-1] > v3.iloc[-1])}
    out["leads"] = {t: {p: out["peers"].get(p, {}).get("chg_pct") for p in PEERS.get(t, [])} for t in tickers}
    # Crypto trades all weekend. Tested 2022-2026: bitcoin's weekend move hints at Monday's opening gap for the trio
    # (corr ~0.25-0.29) and that gap tends to partly fade after the open (-0.09 to -0.17). No link beyond general
    # risk mood (~0 after removing the Nasdaq) and no next-day signal. Context only, not a trading rule.
    try:
        btc = yf.download("BTC-USD", period="10d", auto_adjust=True, progress=False)["Close"]
        btc = btc.iloc[:, 0] if hasattr(btc, "columns") else btc
        import datetime as _dt
        last_fri = btc[btc.index.weekday == 4]
        if len(last_fri):
            out["crypto_weekend"] = {"btc_since_friday_pct": round(float(btc.iloc[-1] / last_fri.iloc[-1] - 1) * 100, 2),
                                     "note": "Weekend bitcoin moves hint at Monday's opening gap for the trio; the gap tends to partly fade after the open."}
    except Exception:
        pass
    return out


# ------------------------------------------------------------------ calendar
FOMC_FALLBACK = ["2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-16", "2027-07-28", "2027-09-22", "2027-11-03", "2027-12-15"]


@soft
def fomc_dates(cache):
    c = cache.get("fomc")
    if c and c.get("fetched") == str(dt.date.today()):
        return c["dates"]
    try:
        html = _get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", as_json=False)
        dates = []
        for year, block in re.findall(r"(\d{4}) FOMC Meetings(.*?)(?=\d{4} FOMC Meetings|$)", html, re.S):
            for mon, days in re.findall(r'fomc-meeting__month[^>]*><strong>(\w+)</strong>.*?fomc-meeting__date[^>]*>([\d\-]+)', block, re.S):
                last_day = days.split("-")[-1]
                try:
                    dates.append(str(dt.datetime.strptime(f"{mon[:3]} {last_day} {year}", "%b %d %Y").date()))
                except ValueError:
                    pass
        dates = sorted(set(dates)) or FOMC_FALLBACK
    except Exception:
        dates = FOMC_FALLBACK
    cache["fomc"] = {"fetched": str(dt.date.today()), "dates": dates}
    return dates


@soft
def calendar(cache, earnings):
    import exchange_calendars as xc
    cal = xc.get_calendar("XNYS")
    today = pd.Timestamp(dt.date.today())
    end = today + pd.Timedelta(days=21)
    sessions = cal.sessions_in_range(today, end)
    sched = cal.schedule.loc[today:end]
    early = [str(d.date()) for d, r in sched.iterrows() if r.close.tz_convert("America/New_York").hour < 16]
    holidays = [str(d.date()) for d in pd.bdate_range(today, end) if d not in sessions]
    nxt = sessions[1] if len(sessions) > 1 and sessions[0] == today else (sessions[0] if len(sessions) else None)
    pre_holiday = bool(nxt is not None and any(today < pd.Timestamp(h) < nxt + pd.Timedelta(days=1) for h in holidays)
                       or str(today.date()) in early)
    fomc = [d for d in fomc_dates(cache) if str(today.date()) <= d <= str(end.date())] if isinstance(fomc_dates(cache), list) else []
    third_fri = [str(d.date()) for d in pd.date_range(today, end, freq="WOM-3FRI")]
    # Seasonal note (tested in research/holiday_lab.py, 1950-2026): "Sell Rosh Hashanah, buy Yom Kippur".
    # S&P fell in that ~7-day window 51% of years vs 42% for random windows (avg -0.25% vs +0.25%); CCJ 59%.
    # A mild tilt, a coin flip in any single year: context for agents, not a rule.
    seasonal = None
    try:
        from convertdate import hebrew
        hy = today.year + 3761
        rh = dt.date(*hebrew.to_gregorian(hy, 7, 1)); yk = dt.date(*hebrew.to_gregorian(hy, 7, 10))
        if rh - dt.timedelta(days=3) <= today.date() <= yk:
            seasonal = (f"Rosh Hashanah ({rh}) to Yom Kippur ({yk}) window: historically a mild down tilt "
                        "(S&P down 51% of years vs 42% normally; CCJ 59%). Not reliable in any single year.")
    except Exception:
        pass
    return {"market_open_today": today in sessions, "holidays_next_3w": holidays, "half_days_next_3w": early,
            "seasonal_note": seasonal,
            "pre_holiday_session": pre_holiday, "fomc_next_3w": fomc, "monthly_opex_next_3w": third_fri,
            "earnings": earnings}


# ------------------------------------------------------------------ all together
def morning_brief(cfg, cache, prices, earnings):
    t0 = time.time()
    T = cfg["tickers"]
    brief = {"built": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "tickers": {}}
    brief["market"] = overnight_and_regime(T)
    brief["calendar"] = calendar(cache, earnings)
    sv = short_volume(T, cache)
    rd = reddit(T)
    for t in T:
        brief["tickers"][t] = {
            "price": prices.get(t),
            "options": options_positioning(t, prices[t]),
            "short_volume": sv.get(t) if isinstance(sv, dict) and "error" not in sv else sv,
            "fundamentals": fundamentals(t),
            "insiders": insiders(t, cfg["sec_cik"][t], cache) if cfg["sec_cik"].get(t) else None,
            "reddit": rd.get(t) if isinstance(rd, dict) and "error" not in rd else rd,
            "reddit_note": "Retail herding spikes tend to reverse over 5-20 days: a buzz surge is a don't-chase flag.",
        }
    brief["seconds"] = round(time.time() - t0, 1)
    return brief
