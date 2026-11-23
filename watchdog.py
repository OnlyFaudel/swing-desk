"""Missed-job watchdog: every scheduled job has a time it should have run by. If it hasn't, the owner's phone
buzzes and the job gets one automatic retry (its done-flag is cleared so the normal scheduler runs it again).

Why: on Nov 20 a test run used up Friday's real review, so the Strategist, Drift Monitor and weekly lessons
silently skipped a week. Nobody noticed for three days. This catches that on the day.
"""
import datetime as dt

# name, flag key (or a special check), deadline (ET, end-of-day jobs use the early-close clock), days (0=Mon), can retry until
JOBS = [
    ("Pre-market check-in", "premarket:{d}", dt.time(7, 30), range(5), dt.time(9, 20)),
    ("Weather check", "weather:{d}", dt.time(8, 0), range(7), dt.time(20, 0)),
    ("Morning meeting (9:00)", "@morning_prep", dt.time(9, 20), range(5), dt.time(9, 28)),
    ("Plant report", "plantrep:{d}", dt.time(9, 30), range(5), dt.time(15, 0)),
    ("Orders at the open", "@morning_done", dt.time(9, 50), range(5), dt.time(11, 0)),
    ("Park idle cash in SPY", "park:{d}", dt.time(15, 59), range(5), None),
    ("Close routine", "@close_done", dt.time(15, 59), range(5), None),
    ("Evening review", "@review_done", dt.time(16, 40), range(5), dt.time(18, 50)),
    ("Weekly strategy and drift check", "@weekly_review", dt.time(16, 45), (4,), dt.time(18, 50)),
    ("Mistakes review", "mistakes:{d}", dt.time(17, 0), (4,), dt.time(22, 0)),
    ("Nuclear Weekly", "weekly:{d}", dt.time(17, 30), (4,), dt.time(22, 0)),
    ("Results reader", "earnread:{d}", dt.time(18, 0), range(7), dt.time(22, 0)),
    ("Sprott uranium update", "sput:{d}", dt.time(18, 45), range(5), dt.time(22, 0)),
    ("Red team", "redteam:{d}", dt.time(17, 30), (6,), dt.time(22, 0)),
]


def _done(st, key, d):
    f = st.get("flags", {})
    if key == "@morning_prep":
        m = st.get("morning") or {}
        return m.get("date") == d and m.get("prepped")
    if key == "@morning_done":
        return f.get("morning_done") == d
    if key == "@close_done":
        return f.get("close_done") == d
    if key == "@review_done":
        return f.get("review_done") == d
    if key == "@weekly_review":
        return f.get("weekly_review_done") == d
    return bool(f.get(key.format(d=d)))


def _clear(st, key, d):
    f = st["flags"]
    if key == "@morning_prep":
        st["morning"] = {}
    elif key.startswith("@"):
        f.pop({"@morning_done": "morning_done", "@close_done": "close_done", "@review_done": "review_done",
               "@weekly_review": "weekly_review_done"}[key], None)
        if key == "@weekly_review":
            f.pop("review_done", None)
    else:
        f.pop(key.format(d=d), None)


def check(st, now, cclock, is_holiday, notify, post):
    """Call every cycle. Returns what was flagged this call (one phone alert per call, however many jobs)."""
    d, t = str(now.date()), now.time()
    if is_holiday(now.date()):
        return []
    ran = st.setdefault("watchdog", {})
    since = st.setdefault("watchdog_since", now.strftime("%Y-%m-%d %H:%M"))  # don't flag jobs that were due before the watchdog existed
    out = []
    for name, key, due, days, retry_until in JOBS:
        if now.weekday() not in days:
            continue
        clock = cclock(now) if due >= dt.time(15, 50) and due < dt.time(16, 0) else t
        if clock < due or _done(st, key, d) or f"{d} {due:%H:%M}" <= since:
            continue
        k = f"{name}:{d}"
        if ran.get(k):
            continue
        ran[k] = True
        retry = bool(retry_until and t < retry_until)
        if retry:
            _clear(st, key, d)
        out.append(f"{name} (due {due:%-I:%M %p}): " + ("retrying now" if retry else "too late to retry today, runs next time"))
    if out:
        notify("Missed job" + ("s" if len(out) > 1 else "") + ": " + ", ".join(o.split(" (")[0] for o in out)[:120],
               "; ".join(out)[:400])
        post("These scheduled jobs didn't run on time: " + "; ".join(out) + ".")
    for k in [k for k in ran if k.split(":")[-1] < str(now.date() - dt.timedelta(days=10))]:
        del ran[k]
    st["watchdog_last"] = now.strftime("%Y-%m-%d %H:%M")
    return out
