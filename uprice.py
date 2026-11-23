"""The uranium price itself: monthly spot and long-term contract prices (industry averages of UxC and TradeTech month-end
prices) that Cameco publishes free, back to 1988. Spot = what a pound costs today; long-term = what utilities sign for
years ahead, which is what CCJ actually sells at. memory/intel/uranium_price.json"""
import json, os, re, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "memory", "intel", "uranium_price.json")
URL = "https://www.cameco.com/invest/markets/uranium-price"


def run():
    h = urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 SwingDesk research"}), timeout=40).read().decode("utf-8", "ignore")
    t = re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", " ", h, flags=re.S))
    rows = re.findall(r"(\d{4})/(\d{2})/\d{2}\s+([\d.]+)(?:\s+([\d.]+))?(?=\s+\d{4}/|\s+[A-Z])", t)  # date, spot, long-term
    series = [{}, {}]
    for y, m, s, lt in rows:
        series[0][f"{y}-{m}"] = float(s)
        if lt:
            series[1][f"{y}-{m}"] = float(lt)
    out = {"spot": series[0], "long_term": series[1], "source": "Cameco (UxC/TradeTech averages)"}
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    json.dump(out, open(PATH, "w"), separators=(",", ":"))
    _events(out)
    return summary(out)


def _events(d, move=7.0):
    """Big monthly price moves and new long-term highs become sector events (dated the month's end) for the discovery engine."""
    import calendar, archive
    ev = archive._load(archive.EVENTS, [])
    seen = {(e["date"], e["type"]) for e in ev if e.get("source") == "uranium price"}
    for k, label in (("spot", "spot"), ("long_term", "long-term")):
        s = d.get(k) or {}
        ks = sorted(s)
        hi = 0
        for a, b in zip(ks, ks[1:]):
            hi = max(hi, s[a])
            y, m = map(int, b.split("-")); date = f"{b}-{calendar.monthrange(y, m)[1]:02d}"
            if date < "2019-01-01":
                continue
            ch = (s[b] / s[a] - 1) * 100
            for typ, ok, title in ((f"uranium_{k}_jump", ch >= move, f"Uranium {label} price up {ch:.1f}% in the month to ${s[b]}"),
                                   (f"uranium_{k}_drop", ch <= -move, f"Uranium {label} price down {ch:.1f}% in the month to ${s[b]}"),
                                   (f"uranium_{k}_new_high", s[b] > hi and k == "long_term", f"Uranium long-term price at a new high: ${s[b]}")):
                if ok and (date, typ) not in seen:
                    seen.add((date, typ))
                    ev.append({"ticker": "_basket", "date": date, "title": title, "type": typ, "source": "uranium price",
                               "r0": None, "r1": None, "r5": None, "r20": None, "r60": None, "x5": None, "x20": None})
    archive._save(archive.EVENTS, ev)


def summary(d=None):
    d = d or (json.load(open(PATH)) if os.path.exists(PATH) else {})
    out = {}
    for k in ("spot", "long_term"):
        s = d.get(k) or {}
        if not s:
            continue
        ks = sorted(s); last = ks[-1]; v = s[last]
        ago = lambda n: s[ks[-1 - n]] if len(ks) > n else None
        out[k] = {"month": last, "usd_per_lb": v, "1m_change_pct": round((v / ago(1) - 1) * 100, 1) if ago(1) else None,
                  "12m_change_pct": round((v / ago(12) - 1) * 100, 1) if ago(12) else None,
                  "5y_high": max(s[x] for x in ks[-60:]), "all_time_high": max(s.values()), "last_12": {x: s[x] for x in ks[-12:]}}
    if out.get("spot") and out.get("long_term"):
        out["spot_minus_long_term"] = round(out["spot"]["usd_per_lb"] - out["long_term"]["usd_per_lb"], 2)
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=1)[:1500])
