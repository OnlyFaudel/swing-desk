"""Weather watch for the power companies: 7-day forecasts for Texas (ERCOT: Dallas + Houston) and PJM (Philadelphia +
Chicago). Tested 2019-2026 (realized extremes vs the stocks' next 5 days relative to our group): PJM heat (avg high
93F+), 3 days ahead: CEG/TLN/VST +1.4% (69% beat, n=26, both halves positive, still a small sample); Texas extremes were
NEGATIVE for VST (heat -1.0%, cold -3.0% 3 days ahead, small samples): extreme Texas cold is a known risk (Winter Storm
Uri, Feb 2021, cost Vistra over $1 billion). Context for the team, not a trade."""
import json, urllib.request

CITIES = {"Texas (ERCOT)": [(32.78, -96.80), (29.76, -95.37)], "PJM (mid-Atlantic/Midwest)": [(39.95, -75.17), (41.88, -87.63)]}
LIMITS = {"Texas (ERCOT)": {"heat": 100, "cold": 25}, "PJM (mid-Atlantic/Midwest)": {"heat": 93, "cold": 12}}
WHO = {"Texas (ERCOT)": ["VST"], "PJM (mid-Atlantic/Midwest)": ["CEG", "TLN", "VST"]}


def forecast():
    out = {}
    for region, pts in CITIES.items():
        days = None
        for lat, lon in pts:
            u = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_max,temperature_2m_min"
                 "&temperature_unit=fahrenheit&timezone=America%2FNew_York&forecast_days=7")
            d = json.load(urllib.request.urlopen(u, timeout=30))["daily"]
            rows = list(zip(d["time"], d["temperature_2m_max"], d["temperature_2m_min"]))
            days = rows if days is None else [(a[0], (a[1] + b[1]) / 2, (a[2] + b[2]) / 2) for a, b in zip(days, rows)]
        lim = LIMITS[region]
        ext = [{"date": t, "high_f": round(h), "low_f": round(l), "kind": "heat" if h >= lim["heat"] else "cold"}
               for t, h, l in days if h >= lim["heat"] or l <= lim["cold"]]
        out[region] = {"stocks": WHO[region], "next7": [{"date": t, "high_f": round(h), "low_f": round(l)} for t, h, l in days],
                       "extremes": ext}
    return out
