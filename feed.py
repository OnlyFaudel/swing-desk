"""The Feed: every agent and every code role posts here in plain words, like a social timeline.
Posts are buffered in memory during a cycle and flushed into state["feed"] at the end (cheap: no extra calls)."""
import datetime as dt, json
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _now():
    """Eastern time, whatever clock the machine running the bot uses (GitHub runs on UTC)."""
    return dt.datetime.now(ET)

BUF = []
THREADS = []
CUR = None
CAP = 1500
PRACTICE = False  # set when agents run in scripted practice mode

# who -> (display name, one-line bio, avatar colour index 1-8)
PEOPLE = {
    "owner":     ("You", "the owner", 2),
    "chief":     ("Desk Chief", "runs the morning and the lineup", 1),
    "exec":      ("Execution Trader", "places, fills and stops orders", 2),
    "officer":   ("Account Officer", "cash, settlement, brakes, books vs broker", 3),
    "nowcast":   ("Nowcast", "reads Asia's close before the open", 4),
    "drift":     ("Drift Monitor", "checks live results against the research", 5),
    "gate":      ("Promotion Gate", "decides when real money is allowed", 6),
    "shadow":    ("Shadow Desk", "practice trades on 52 stocks, no money", 7),
    "options":   ("Options Recorder", "saves every option price, every day", 8),
    "scout":     ("News Scout", "scores headlines", 1),
    "investigator": ("News Investigator", "digs into the headlines that matter", 2),
    "filings":   ("Filings Reader", "SEC filings: contracts, insiders, dilution", 3),
    "level":     ("Level Analyst", "judges each support level", 4),
    "technical": ("Technician", "charts and indicators", 6),
    "pm":        ("Portfolio Manager", "final call on news: hold, exit, or skip", 1),
    "core":      ("Core Holdings", "the long-term CCJ position", 5),
    "review":    ("Reviewer", "end-of-day review", 8),
    "macro":     ("Macro Analyst", "market mood, calendar, risk level", 3),
    "whale":     ("Whale Watcher", "options flow, short volume, insiders", 4),
    "crowd":     ("Crowd Reader", "Reddit and analyst chatter", 5),
    "risk":      ("Risk Manager", "vetoes bad setups", 7),
    "auditor":   ("Auditor", "weekly scorecard", 1),
    "strategist": ("Strategist", "weekly theses", 2),
    "postmortem": ("Postmortem", "why a trade won or lost", 3),
    "researcher": ("Research Lead", "proposes ideas and writes the notebook", 5),
    "system":    ("System", "plumbing and errors", 8),
}

TITLE_WHO = [("ARMED", "exec"), ("FILLED", "exec"), ("BOUGHT", "exec"), ("SOLD", "exec"), ("STOP", "exec"),
             ("Order", "exec"), ("EXIT", "exec"), ("News ", "scout"), ("Desk on", "pm"), ("Morning brief", "chief"), ("Lineup", "chief"),
             ("Daily review", "review"), ("Open watch", "nowcast"), ("Signal drift", "drift"),
             ("Promotion gate", "gate"), ("Live buys blocked", "gate"), ("KILL", "officer"), ("Books", "officer"),
             ("Strategist", "strategist"), ("Huddle", "pm"), ("Radar", "options"), ("Options", "options"), ("Agent desk", "system")]


def who_for_title(title):
    for prefix, who in TITLE_WHO:
        if title.upper().startswith(prefix.upper()):
            return who
    return "chief"


def post(who, text, tickers=(), kind="note", title=None, art=None):
    """A public announcement on the main feed. art = {"big": "...", "sub": "..."} for the picture block."""
    if who not in PEOPLE:
        PEOPLE[who] = (who.replace("_", " ").title(), "", 8)
    BUF.append({"t": _now().strftime("%Y-%m-%d %H:%M"), "who": who, "kind": kind, "title": title,
                "text": str(text)[:1200], "tickers": sorted(set(tickers)), "art": art,
                "thread": CUR["id"] if CUR is not None else None})


def norm_who(x):
    """'Risk Manager', 'risk', 'the risk manager' -> 'risk'; unknown -> 'team'."""
    if not x:
        return "team"
    x = str(x).strip().lower().replace("the ", "")
    if x in PEOPLE:
        return x
    for k, v in PEOPLE.items():
        if x == v[0].lower() or x in v[0].lower() or v[0].lower() in x:
            return k
    return "team"


def _flatten(obj, depth=0):
    """Agent JSON -> short readable lines."""
    if depth > 3:
        return []
    lines = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("_"):
                continue
            if isinstance(v, (dict, list)):
                sub = _flatten(v, depth + 1)
                if sub:
                    if k.isupper() and len(k) <= 6:  # a ticker block
                        lines.append(f"{k}: " + "; ".join(sub)[:300])
                    else:
                        lines.extend(sub)
            elif v not in (None, "", [], {}):
                lines.append(f"{k.replace('_', ' ')}: {v}" if depth or k not in ("summary", "headline", "note", "market_note", "thesis") else str(v))
    elif isinstance(obj, list):
        for x in obj[:6]:
            lines.extend(_flatten(x, depth + 1))
    elif obj not in (None, ""):
        lines.append(str(obj))
    return lines


class thread:
    """Group chat for one decision: every agent call and code role inside it becomes a message."""
    def __init__(self, title, tickers=(), kind="decision"):
        self.t = {"id": _now().strftime("%Y%m%d%H%M%S%f"), "title": title, "tickers": sorted(set(tickers)),
                  "kind": kind, "start": _now().strftime("%Y-%m-%d %H:%M"), "msgs": [], "practice": PRACTICE}

    def __enter__(self):
        global CUR
        self.prev, CUR = CUR, self.t
        THREADS.append(self.t)
        return self.t

    def __exit__(self, *a):
        global CUR
        CUR = self.prev
        if CUR is None or CUR is not self.t:
            self.t["end"] = _now().strftime("%H:%M")


def say(who, text, outcome=False, to="team", notes=None):
    if CUR is None:
        return False
    if who not in PEOPLE:
        PEOPLE[who] = (who.replace("_", " ").title(), "", 8)
    to = norm_who(to)
    m = {"t": _now().strftime("%H:%M"), "who": who, "to": to if to != who else "team",
         "text": str(text)[:900], "outcome": outcome}
    if notes:
        m["notes"] = str(notes)[:900]
    CUR["msgs"].append(m)
    return True


def teammates():
    if CUR is None:
        return []
    return [f"{PEOPLE.get(m['who'], (m['who'],))[0]}: {m['text']}" for m in CUR["msgs"]][-8:]


def post_agent(role, out, to=None):
    if not isinstance(out, dict):
        return
    out = {k: v for k, v in out.items() if not str(k).startswith("_") or (k == "_raw" and v)}  # cost/debug fields stay out of the chat
    if not out or (set(out) == {"_raw"} and not str(out["_raw"]).strip()):
        return  # an empty answer is not posted (never show raw code in the chat)
    if CUR is not None:  # inside a discussion: it is a chat message (+ the agent's own notes), not a public post
        notes = "\n".join(_flatten({k: v for k, v in out.items() if k not in ("say", "to", "_raw")}))[:900]
        say(role, out.get("say") or notes[:600] or str(out.get("_raw", ""))[:300], to=out.get("to") or to or "team",
            notes=notes if out.get("say") else None)
        return
    if role == "scout" and not any((i.get("materiality") or 0) >= 7 for i in (out.get("items") or []) if isinstance(i, dict)):
        return
    tick = [k for k in (out.get("tickers") or {}) if isinstance(k, str)] if isinstance(out.get("tickers"), dict) else []
    txt = (out.get("say") + "\n\n" if out.get("say") else "") + "\n".join(_flatten({k: v for k, v in out.items() if k != "say"}))
    post(role, txt[:1200] or json.dumps(out, default=str)[:400], tick, kind="agent")


def flush(st):
    done = [t for t in THREADS if t["msgs"]]
    if done:
        st.setdefault("chats", []).extend(done)
        del st["chats"][:-300]
    THREADS.clear()
    if BUF:
        st.setdefault("feed", []).extend(BUF)
        BUF.clear()
        del st["feed"][:-CAP]
    st["feed_people"] = {k: {"name": v[0], "bio": v[1], "c": v[2]} for k, v in PEOPLE.items()}
