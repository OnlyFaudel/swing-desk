"""Owner posts: the owner writes to the team from the page (or the ntfy app) and the desk scans for a trade right away.

Transport: ntfy topic "<NTFY_TOPIC>-inbox" (no key, no server). The page posts there; each bot run polls it.
Anyone who knows the topic could post, which is why a post can only ask the team to LOOK: every buy still has to
be a real support setup with a stop, and posts per day are capped (agent budget caps still apply)."""
import json, os, urllib.request


def topic():
    t = os.environ.get("NTFY_TOPIC")
    return f"{t}-inbox" if t else None


LOCAL = []  # posts injected on the command line: python run.py owner-post "look at CCJ now"


def poll(since="24h"):
    tp = topic()
    if not tp:
        return list(LOCAL)
    url = f"https://ntfy.sh/{tp}/json?poll=1&since={since}"
    raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "swing-desk"}), timeout=15).read()
    out = []
    for line in raw.decode("utf-8", "ignore").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("event") == "message" and e.get("message"):
            out.append({"id": e["id"], "time": e.get("time", 0), "text": e["message"][:500]})
    return out + list(LOCAL)
