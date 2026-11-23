"""The people and the money behind each stock: every boss on file (title, pay, age), what insiders do with their own
shares, who owns the company, what analysts did (upgrades/downgrades over the years), governance risk scores and the
financial basics. Weekly refresh. Insider trades and analyst actions also become dated events, so the discovery engine
tests them ("a CFO sold $3M: what did the stock do next?").

memory/people/<TICKER>.json   the full file per company
memory/people_events.json     insider buys/sells and analyst upgrades/downgrades as events
"""
import datetime as dt, json, os

ROOT = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(ROOT, "memory", "people")
EVENTS = os.path.join(ROOT, "memory", "people_events.json")
FIN = ["marketCap", "enterpriseValue", "totalRevenue", "revenueGrowth", "grossMargins", "operatingMargins", "profitMargins", "ebitda",
       "totalCash", "totalDebt", "debtToEquity", "freeCashflow", "operatingCashflow", "trailingPE", "forwardPE", "priceToBook",
       "sharesOutstanding", "floatShares", "shortPercentOfFloat", "shortRatio", "heldPercentInsiders", "heldPercentInstitutions",
       "targetMeanPrice", "targetHighPrice", "targetLowPrice", "recommendationKey", "numberOfAnalystOpinions", "beta",
       "fullTimeEmployees", "dividendYield", "earningsTimestamp"]
RISK = {"auditRisk": "audit", "boardRisk": "board", "compensationRisk": "pay", "shareHolderRightsRisk": "shareholder rights", "overallRisk": "overall"}


def _rows(df, n=200):
    if df is None or not hasattr(df, "to_dict") or not len(df):
        return []
    df = df.reset_index().head(n)
    return json.loads(df.to_json(orient="records", date_format="iso"))


def one(t):
    import yfinance as yf
    tk = yf.Ticker(t)
    info = tk.info or {}
    officers = [{k: o.get(k) for k in ("name", "title", "age", "totalPay", "yearBorn")} for o in info.get("companyOfficers", [])]
    ins = _rows(getattr(tk, "insider_transactions", None), 300)
    trades = []
    for r in ins:
        text = (r.get("Text") or "").lower()
        kind = "buy" if "purchase" in text or "buy" in text else "sell" if "sale" in text else "award/other"
        trades.append({"date": (r.get("Start Date") or "")[:10], "who": r.get("Insider"), "role": r.get("Position"), "kind": kind,
                       "shares": r.get("Shares"), "value_usd": r.get("Value"), "what": r.get("Text")})
    ana = _rows(getattr(tk, "upgrades_downgrades", None), 400)
    analysts = [{"date": (r.get("GradeDate") or r.get("index") or "")[:10], "firm": r.get("Firm"), "action": r.get("Action"),
                 "from": r.get("FromGrade"), "to": r.get("ToGrade"), "target": r.get("currentPriceTarget")} for r in ana]
    holders = _rows(getattr(tk, "institutional_holders", None), 15)
    year_ago = str(dt.date.today() - dt.timedelta(days=365))
    sold = sum((x["value_usd"] or 0) for x in trades if x["kind"] == "sell" and x["date"] >= year_ago)
    bought = sum((x["value_usd"] or 0) for x in trades if x["kind"] == "buy" and x["date"] >= year_ago)
    def _is_ceo(o):
        ti = (o.get("title") or "").lower()
        return "ceo" in ti.replace("ceo,", "ceo ").split() or "ceo" in ti or "chief executive" in ti
    ceo = next((o for o in officers if _is_ceo(o)), None) or next(
        (o for o in officers if "president" in (o.get("title") or "").lower() and "vice" not in (o.get("title") or "").lower()
         and "vp" not in (o.get("title") or "").lower() and " of " not in (o.get("title") or "").lower()), None)
    if ceo is None:
        ceo = {"name": None, "note": "The data source doesn't list this company's chief executive right now; check the latest filings."}
    return {"ticker": t, "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "name": info.get("longName"),
            "about": (info.get("longBusinessSummary") or "")[:1500], "website": info.get("website"), "hq": ", ".join(x for x in (info.get("city"), info.get("state"), info.get("country")) if x),
            "bosses": officers, "ceo": ceo,
            "governance_risk_1_low_10_high": {lab: info.get(k) for k, lab in RISK.items() if info.get(k) is not None},
            "insiders_last_12m": {"sold_usd": round(sold), "bought_usd": round(bought), "net_usd": round(bought - sold),
                                  "sellers": sorted({x["who"] for x in trades if x["kind"] == "sell" and x["date"] >= year_ago})},
            "insider_trades": trades[:80], "top_holders": holders,
            "analysts": {"latest": analysts[:25], "upgrades_12m": sum(1 for a in analysts if a["date"] >= year_ago and (a["action"] or "").lower() == "up"),
                         "downgrades_12m": sum(1 for a in analysts if a["date"] >= year_ago and (a["action"] or "").lower() == "down"),
                         "target_mean": info.get("targetMeanPrice"), "rating": info.get("recommendationKey"), "count": info.get("numberOfAnalystOpinions")},
            "financials": {k: info.get(k) for k in FIN if info.get(k) is not None}}, trades, analysts


def run(tickers):
    os.makedirs(DIR, exist_ok=True)
    ev, seen, out = [], set(), {}
    for t in tickers:
        try:
            d, trades, analysts = one(t)
        except Exception as e:
            print("people", t, e); continue
        json.dump(d, open(os.path.join(DIR, f"{t}.json"), "w"), indent=0, default=str)
        out[t] = {"ceo": (d["ceo"] or {}).get("name"), "net_insider_usd_12m": d["insiders_last_12m"]["net_usd"]}
        for x in trades:
            if x["kind"] in ("buy", "sell") and x["date"] and (x["value_usd"] or 0) >= 50_000:  # real money, not small grants
                key = (t, x["date"], x["kind"])
                if key not in seen:
                    seen.add(key)
                    ev.append({"ticker": t, "date": x["date"], "title": f"{x['who']} ({x['role']}) {x['kind']}s ${x['value_usd']:,.0f} of {t}",
                               "type": f"insider_{x['kind']}", "source": "insider filings",
                               "r0": None, "r1": None, "r5": None, "r20": None, "r60": None, "x5": None, "x20": None})
        for a in analysts:
            act = (a["action"] or "").lower()
            if act in ("up", "down", "init") and a["date"]:
                typ = {"up": "analyst_upgrade", "down": "analyst_downgrade", "init": "analyst_new_coverage"}[act]
                key = (t, a["date"], typ)
                if key not in seen:
                    seen.add(key)
                    ev.append({"ticker": t, "date": a["date"], "title": f"{a['firm']}: {a['action']} {a['from'] or ''} -> {a['to'] or ''}".strip(),
                               "type": typ, "source": "analysts", "r0": None, "r1": None, "r5": None, "r20": None, "r60": None, "x5": None, "x20": None})
    json.dump(ev, open(EVENTS, "w"), separators=(",", ":"))
    _scorecards(list(out))
    return out, len(ev)


def _scorecards(tickers):
    """Are the bosses doing their job? Stock vs the rest of the group over 1 and 3 years, pay, and their own buying/selling."""
    try:
        import yfinance as yf
        px = yf.download(tickers, period="3y", auto_adjust=True, progress=False)["Close"]
    except Exception as e:
        print("scorecard prices", e); return
    def ret(s, days):
        s = s.dropna()
        return None if len(s) < days else round((s.iloc[-1] / s.iloc[-days] - 1) * 100, 1)
    r1 = {t: ret(px[t], 252) for t in tickers if t in px}
    r3 = {t: ret(px[t], 740) for t in tickers if t in px}
    for t in tickers:
        path = os.path.join(DIR, f"{t}.json")
        try:
            d = json.load(open(path))
        except Exception:
            continue
        others1 = [v for k, v in r1.items() if k != t and v is not None]
        others3 = [v for k, v in r3.items() if k != t and v is not None]
        ceo = d.get("ceo") or {}
        pay = sum((o.get("totalPay") or o.get("pay") or 0) for o in d.get("bosses") or [])
        ins = d.get("insiders_last_12m") or {}
        med = lambda v: sorted(v)[len(v) // 2] if len(v) % 2 else sum(sorted(v)[len(v) // 2 - 1:len(v) // 2 + 1]) / 2
        g1 = None if r1.get(t) is None or not others1 else round(r1[t] - med(others1), 1)
        g3 = None if r3.get(t) is None or not others3 else round(r3[t] - med(others3), 1)
        verdict = ("ahead of the group" if (g1 or 0) > 10 else "behind the group" if (g1 or 0) < -10 else "in line with the group")
        d["scorecard"] = {"ceo": ceo.get("name"), "ceo_pay_usd": ceo.get("totalPay") or ceo.get("pay"), "top_team_pay_usd": pay or None,
                          "stock_1y_pct": r1.get(t), "group_1y_pct": round(med(others1), 1) if others1 else None, "group_3y_pct": round(med(others3), 1) if others3 else None,
                          "vs_group_1y_pts": g1, "stock_3y_pct": r3.get(t), "vs_group_3y_pts": g3,
                          "insiders_net_usd_12m": ins.get("net_usd"), "verdict_1y": verdict,
                          "how_to_read": "Positive 'vs group' means the stock beat the typical (middle) nuclear name we follow. Heavy insider selling while the stock lags is the warning sign."}
        json.dump(d, open(path, "w"), indent=0, default=str)


def load(t):
    try:
        return json.load(open(os.path.join(DIR, f"{t}.json")))
    except Exception:
        return {}


if __name__ == "__main__":
    print(run(["CCJ", "NXE", "UEC", "DNN", "UUUU", "LEU", "BWXT", "CEG", "VST", "TLN"]))
