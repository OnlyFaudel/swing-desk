"""Workers and jobs: daily open-job counts and new postings from nuclear companies' public job boards (free, official
feeds the companies publish themselves). A sector hiring index: is the industry building teams or cutting?

memory/intel/jobs.json: {"counts": {date: {company: n}}, "seen": {company: [job ids]}, "new": [recent new postings]}
"""
import datetime as dt, json, os, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "memory", "intel", "jobs.json")
BOARDS = {  # company: (board system, board name, the stock it tells us about or "sector")
    "Oklo": ("greenhouse", "oklo", "sector"),
    "Kairos Power": ("greenhouse", "kairospower", "sector"),
    "Valar Atomics": ("greenhouse", "valaratomics", "sector"),
    "Radiant": ("ashby", "radiant", "sector"),
    "Antares": ("ashby", "antares", "sector"),
    "Constellation": ("ashby", "constellation", "CEG"),
}
KEYWORDS = {"fuel": "fuel", "haleu": "HALEU", "enrich": "enrichment", "licens": "licensing", "reactor operator": "reactor operators",
            "construction": "construction", "manufactur": "manufacturing", "uranium": "uranium", "data center": "data centers"}


def _get(kind, name):
    url = {"greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{name}/jobs",
           "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{name}",
           "lever": f"https://api.lever.co/v0/postings/{name}?mode=json"}[kind]
    d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SwingDesk research"}), timeout=20))
    jobs = d.get("jobs") if isinstance(d, dict) else d
    out = []
    for j in jobs or []:
        loc = j.get("location")
        out.append({"id": str(j.get("id") or j.get("jobUrl") or j.get("absolute_url") or j.get("title")), "title": (j.get("title") or j.get("text") or "")[:120],
                    "where": (loc.get("name") if isinstance(loc, dict) else loc) or j.get("locationName") or "",
                    "link": j.get("absolute_url") or j.get("jobUrl") or j.get("hostedUrl")})
    return out


def run():
    db = json.load(open(PATH)) if os.path.exists(PATH) else {"counts": {}, "seen": {}, "new": []}
    today = str(dt.date.today())
    counts = {}
    for co, (kind, name, tk) in BOARDS.items():
        try:
            jobs = _get(kind, name)
        except Exception as e:
            print("jobs", co, e); continue
        counts[co] = len(jobs)
        seen = set(db["seen"].get(co, []))
        if seen:  # first day is the baseline, not "new"
            for j in jobs:
                if j["id"] not in seen:
                    db["new"].append({"date": today, "company": co, "ticker": tk, **{k: j[k] for k in ("title", "where", "link")}})
        db["seen"][co] = [j["id"] for j in jobs]
    if counts:
        db["counts"][today] = counts
    db["new"] = db["new"][-400:]
    for d in sorted(db["counts"])[:-730]:
        del db["counts"][d]
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    json.dump(db, open(PATH, "w"), separators=(",", ":"))
    return summary(db)


def summary(db=None, ticker=None):
    db = db or (json.load(open(PATH)) if os.path.exists(PATH) else {"counts": {}, "new": []})
    days = sorted(db["counts"])
    if not days:
        return {}
    now = db["counts"][days[-1]]
    old = next((db["counts"][d] for d in days if d >= str(dt.date.fromisoformat(days[-1]) - dt.timedelta(days=30))), now)
    total, total_old = sum(now.values()), sum(old.get(k, v) for k, v in now.items())
    new = [n for n in db["new"] if ticker is None or n["ticker"] in (ticker, "sector")][-40:]
    themes = {}
    for n in [n for n in db["new"] if n["date"] >= str(dt.date.today() - dt.timedelta(days=30))]:
        low = n["title"].lower()
        for k, lab in KEYWORDS.items():
            if k in low:
                themes[lab] = themes.get(lab, 0) + 1
    return {"as_of": days[-1], "open_jobs_by_company": now, "sector_open_jobs": total,
            "change_vs_30_days_ago": total - total_old, "days_tracked": len(days),
            "new_postings_30d_by_theme": dict(sorted(themes.items(), key=lambda kv: -kv[1])),
            "latest_new_postings": list(reversed(new))[:15]}


if __name__ == "__main__":
    print(json.dumps(run(), indent=1)[:1500])
