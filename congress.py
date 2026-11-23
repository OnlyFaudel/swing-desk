"""Bills in Congress that touch nuclear power or uranium, with their latest action (introduced, passed a chamber, signed).
Needs a free key from api.congress.gov (sign up at api.data.gov) in the CONGRESS_API_KEY secret; without it this is skipped
and the news collector's "Congress and laws" searches still cover it."""
import datetime as dt, json, os, urllib.error, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "memory", "intel", "congress.json")
WORDS = ("nuclear", "uranium", "reactor", "haleu", "enrichment", "radioactive", "atomic", "fission", "fusion", "critical mineral")


def run(pages=4):
    key = os.environ.get("CONGRESS_API_KEY")
    if not key:
        return None
    db = json.load(open(PATH)) if os.path.exists(PATH) else {"bills": {}}
    for p in range(pages):  # the most recently updated bills, 250 a page; keep the nuclear ones
        q = urllib.parse.urlencode({"api_key": key, "format": "json", "limit": 250, "offset": p * 250, "sort": "updateDate+desc"})
        req = urllib.request.Request(f"https://api.congress.gov/v3/bill?{q}", headers={  # its firewall blocks the default Python agent
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36", "Accept": "application/json"})
        try:
            d = json.load(urllib.request.urlopen(req, timeout=30))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Congress.gov {e.code}: {e.read()[:200].decode('utf-8', 'ignore')}")
        for b in d.get("bills", []):
            title = b.get("title", "")
            if not any(w in title.lower() for w in WORDS):
                continue
            k = f"{b.get('congress')}-{b.get('type')}-{b.get('number')}"
            act = b.get("latestAction") or {}
            old = db["bills"].get(k, {})
            db["bills"][k] = {"title": title[:200], "latest_action": act.get("text", "")[:200], "action_date": act.get("actionDate"),
                              "updated": b.get("updateDate"), "url": b.get("url"),
                              "changed": old.get("latest_action") not in (None, act.get("text", "")[:200])}
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    json.dump(db, open(PATH, "w"), separators=(",", ":"))
    return summary(db)


def summary(db=None):
    db = db or (json.load(open(PATH)) if os.path.exists(PATH) else {"bills": {}})
    bills = sorted(db["bills"].items(), key=lambda kv: kv[1].get("action_date") or "", reverse=True)
    return {"tracked": len(bills), "latest": [{"bill": k, **v} for k, v in bills[:20]]}
