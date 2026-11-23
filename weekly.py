"""Nuclear Weekly: a one-page research note every Friday, published on the site (docs/weekly/) so it can be shared.
The team writes the content as structured sections; this file renders it as a clean, readable page."""
import html, json, os, datetime as dt

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "docs", "weekly")

CSS = """
:root{--paper:#111315;--ink:#ECE8DF;--ink2:#9C9E9A;--hair:#272B2F;--acc:#CDB16A;--gain:#8CC6A0;--loss:#E3877E}
*{box-sizing:border-box}html{background:var(--paper);color:var(--ink);font-family:"Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
body{margin:0;padding:48px 22px 80px}main{max-width:680px;margin:0 auto}
.k{color:var(--acc);font-size:13px;letter-spacing:.02em}
h1{font-family:Newsreader,Georgia,serif;font-weight:500;font-size:46px;line-height:1.05;margin:10px 0 8px;letter-spacing:-.02em}
.by{color:var(--ink2);font-size:14px;margin-bottom:28px}
.lead{font-family:Newsreader,Georgia,serif;font-size:22px;line-height:1.45;margin:0 0 30px}
h2{font-family:Newsreader,Georgia,serif;font-weight:500;font-size:25px;margin:34px 0 8px;padding-top:18px;border-top:1px solid var(--hair)}
p,li{font-size:16.5px;line-height:1.65}ul{padding-left:20px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:8px 0 6px}
.stat{border:1px solid var(--hair);border-radius:12px;padding:12px 14px}.stat b{display:block;font-family:Newsreader,Georgia,serif;font-size:26px;font-weight:500}
.stat span{font-size:12.5px;color:var(--ink2)}
.pos{color:var(--gain)}.neg{color:var(--loss)}
footer{margin-top:44px;padding-top:16px;border-top:1px solid var(--hair);color:var(--ink2);font-size:13px;line-height:1.6}
a{color:var(--acc)}
"""


def _e(x):
    return html.escape(str(x or ""))


def render(note, date):
    secs = "".join(f"<h2>{_e(s.get('title'))}</h2>" + "".join(f"<p>{_e(p)}</p>" for p in (s.get("paragraphs") or []))
                   + (f"<ul>{''.join(f'<li>{_e(b)}</li>' for b in s.get('bullets') or [])}</ul>" if s.get("bullets") else "")
                   for s in note.get("sections") or [])
    stats = "".join(f'<div class="stat"><b class="{_e(s.get("tone", ""))}">{_e(s.get("value"))}</b><span>{_e(s.get("label"))}</span></div>'
                    for s in note.get("stats") or [])
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nuclear Weekly, {date:%B %d, %Y}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400..700&family=Newsreader:opsz,wght@6..72,400..600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><main>
<div class="k">Nuclear Weekly</div><h1>{_e(note.get('headline'))}</h1>
<div class="by">Week ending {date:%B %d, %Y}. Research by the Patient Levels nuclear desk.</div>
<p class="lead">{_e(note.get('summary'))}</p>
{f'<div class="stats">{stats}</div>' if stats else ''}
{secs}
<footer>Written by an AI research desk that tracks the nuclear fuel chain, the plants and the companies every day, and trades a
paper account to test its ideas. Not investment advice. <a href="index.html">All notes</a> &middot; <a href="../">The desk</a></footer>
</main></body></html>"""


def publish(note, date):
    os.makedirs(OUT, exist_ok=True)
    name = f"{date}.html"
    open(os.path.join(OUT, name), "w").write(render(note, date))
    idx_path = os.path.join(OUT, "notes.json")
    try:
        idx = json.load(open(idx_path))
    except Exception:
        idx = []
    idx = [x for x in idx if x["file"] != name] + [{"file": name, "date": str(date), "headline": note.get("headline")}]
    idx.sort(key=lambda x: x["date"], reverse=True)
    json.dump(idx, open(idx_path, "w"), indent=1)
    rows = "".join(f'<p><a href="{_e(x["file"])}">{_e(x["headline"])}</a><br><span style="color:#9C9E9A;font-size:14px">{_e(x["date"])}</span></p>' for x in idx)
    open(os.path.join(OUT, "index.html"), "w").write(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nuclear Weekly</title><link href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400..700&family=Newsreader:opsz,wght@6..72,400..600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><main><div class="k">Archive</div><h1>Nuclear Weekly</h1>
<div class="by">A one-page note on the nuclear and uranium markets, every Friday.</div>{rows}</main></body></html>""")
    return f"weekly/{name}"
