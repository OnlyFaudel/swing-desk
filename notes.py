"""Desk notes: every agent gets the slice of the stock files that fits its seat, and the note checker tracks who uses them.

Each Claude call goes through agents.Desk.ask -> notes.attach(role, payload) adds "desk_notes" for the stocks the
question is about (plus the sector file), and asks the agent to list "notes_used". notes.record() tallies that per
role so the owner can see which agents actually read the files and which ignore them.
"""
import json, os, re, datetime as dt

ROOT = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(ROOT, "memory", "dossiers")
TICKERS = ("CCJ", "NXE", "UEC", "DNN", "UUUU", "LEU", "BWXT", "CEG", "VST", "TLN")

# which parts of the stock file each seat needs (keeps every call small)
SEATS = {
    "macro":        {"stock": ["Snapshot"], "sector": ["Uranium market", "Government and laws", "Countries", "Defense and geopolitics",
                                                       "Big tech power deals", "Discoveries"]},
    "whale":        {"stock": ["Snapshot", "Leadership and insiders", "Ownership and analysts", "Options and big money"], "sector": []},
    "crowd":        {"stock": ["Snapshot", "Crowd", "News"], "sector": []},
    "level":        {"stock": ["Snapshot", "Price behavior", "What history says", "Discoveries", "Our trades"], "sector": []},
    "technical":    {"stock": ["Snapshot", "Price behavior", "What history says"], "sector": []},
    "investigator": {"stock": ["Snapshot", "Legal", "Deals and contracts", "Leadership and insiders", "Filings and company events",
                               "What history says"], "sector": ["Government and laws"]},
    "scout":        {"stock": ["Legal", "Deals and contracts"], "sector": ["Government and laws", "Countries"]},
    "postmortem":   {"stock": ["Snapshot", "News", "What history says", "Our trades"], "sector": []},
    "risk":         {"stock": ["Snapshot", "Legal", "Leadership and insiders", "Discoveries", "Price behavior"],
                     "sector": ["Panic-day record", "Rules the bot follows from its discoveries"]},
    "_default":     {"stock": ["Snapshot", "Leadership and insiders", "Ownership and analysts", "Legal", "Deals and contracts", "Discoveries"],
                     "sector": ["Uranium market", "Rules the bot follows from its discoveries", "Panic-day record"]},
}
SKIP_KEYS = {"bosses", "top_holders", "company_description", "how_to_read", "link", "outlet", "numbers", "posts", "chat"}
ASK = (" The payload has desk_notes: the desk's files on these stocks and the sector (bosses, insiders, analysts, lawsuits, "
       "deals, history, discoveries, uranium price). Use them when they matter and never contradict them without saying why. "
       'Add "notes_used": [the names of the notes you actually relied on, e.g. "CCJ Legal", "SECTOR Uranium market"] to your JSON '
       "(empty list if none).")


def _load(p, default):
    try:
        return json.load(open(p))
    except Exception:
        return default


def _trim(x, depth=0, n=3, s=120):
    """Shrink a note: short lists, short strings, no noisy keys."""
    if depth > 4:
        return None
    if isinstance(x, dict):
        return {k: _trim(v, depth + 1, n, s) for k, v in list(x.items())[:8] if k not in SKIP_KEYS and v not in (None, [], {}, "")}
    if isinstance(x, list):
        return [_trim(v, depth + 1, n, s) for v in x[:n]]
    if isinstance(x, str):
        return x[:s]
    if isinstance(x, float):
        return round(x, 2)
    return x


def tickers_in(payload, limit=3):
    txt = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    counts = {t: len(re.findall(rf"\b{t}\b", txt)) for t in TICKERS}
    return [t for t, c in sorted(counts.items(), key=lambda kv: -kv[1]) if c][:limit]


def build(role, payload, cap=3500):
    seat = SEATS.get(role, SEATS["_default"])
    raw = {}
    for t in tickers_in(payload):
        S = _load(os.path.join(DIR, f"{t}.json"), {}).get("sections", {})
        for sec in seat["stock"]:
            if S.get(sec):
                raw[f"{t} {sec}"] = S[sec]
    S = _load(os.path.join(DIR, "SECTOR.json"), {}).get("sections", {})
    for sec in seat["sector"]:
        if S.get(sec):
            raw[f"SECTOR {sec}"] = S[sec]
    for n, s in ((3, 120), (2, 90), (1, 70)):  # shrink every note before dropping any
        out = {k: _trim(v, 0, n, s) for k, v in raw.items()}
        if len(json.dumps(out, default=str)) <= cap:
            return out
    while out and len(json.dumps(out, default=str)) > cap:  # stay cheap: drop the last-listed notes first
        out.pop(list(out)[-1])
    return out


def attach(role, system, payload):
    """Returns (system, payload) with the notes added. Strings get the notes appended as text."""
    if isinstance(payload, dict) and ("everything_we_know" in payload or "desk_notes" in payload):
        return system + ASK, payload
    try:
        notes = build(role, payload)
    except Exception as e:
        print("notes", e)
        return system, payload
    if not notes:
        return system, payload
    if isinstance(payload, dict):
        return system + ASK, {**payload, "desk_notes": notes}
    return system + ASK, f"{payload}\n\nDESK NOTES:\n{json.dumps(notes, default=str)}"


def record(state, role, out, offered):
    """The note checker: per role, how often notes were offered, how often used, and which ones."""
    a = state.setdefault("notes_audit", {})
    r = a.setdefault(role, {"asked": 0, "used": 0, "notes": {}, "since": str(dt.date.today())})
    if not offered:
        return
    r["asked"] += 1
    used = out.pop("notes_used", None) if isinstance(out, dict) else None
    if isinstance(used, list) and used:
        r["used"] += 1
        for n in used[:8]:
            n = str(n)[:60]
            r["notes"][n] = r["notes"].get(n, 0) + 1
        out["_notes_used"] = used[:8]


def report(state, min_asked=3):
    """Plain-English note check for the feed."""
    a = state.get("notes_audit") or {}
    rows = []
    for role, r in sorted(a.items(), key=lambda kv: -kv[1]["asked"]):
        if r["asked"] < min_asked:
            continue
        share = r["used"] / r["asked"]
        top = [n for n, _ in sorted(r["notes"].items(), key=lambda kv: -kv[1])[:3]]
        rows.append((role, share, r["asked"], top))
    return rows
