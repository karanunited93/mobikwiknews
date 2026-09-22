#!/usr/bin/env python3
"""
MobiKwik Finance Desk — static daily builder.

Pulls India + global finance news from public RSS feeds, drafts an X and an
Instagram post per story, and writes a self-contained black-and-white page to
public/index.html. Runs in GitHub Actions once a day (and on demand).

Drafting: uses Google's Gemini free tier if GEMINI_API_KEY is set; otherwise
falls back to simple template posts so the page still builds with zero cost and
zero signup.
"""

import os
import re
import html
import json
import datetime
import urllib.request
import urllib.error

import feedparser

# ------------------------------------------------------------------ config
BRAND = "MobiKwik"
BRAND_CONTEXT = (
    "MobiKwik is a major Indian fintech app: UPI payments, wallet, bill "
    "payments & recharges, ZIP pay-later, and Xtra investing."
)

# Public RSS feeds. Any that 404 or return nothing are skipped automatically —
# add or swap freely.
INDIA_FEEDS = [
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.livemint.com/rss/markets",
    "https://www.moneycontrol.com/rss/business.xml",
    "https://www.moneycontrol.com/rss/economy.xml",
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://www.financialexpress.com/market/feed/",
]
GLOBAL_FEEDS = [
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",   # CNBC top news
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",    # CNBC economy
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",
]

PER_LANE = 8            # stories kept per column
MAX_AGE_HOURS = 40      # ignore anything older than this

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
NOW = datetime.datetime.now(datetime.timezone.utc)


# ------------------------------------------------------------------ fetch
def clean_text(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return html.unescape(s).strip()


def fetch_feed(url):
    out = []
    try:
        d = feedparser.parse(url)
    except Exception as e:
        print(f"  ! failed {url}: {e}")
        return out
    src = clean_text(d.feed.get("title", "")) if getattr(d, "feed", None) else ""
    for e in d.entries:
        title = clean_text(e.get("title", ""))
        if not title:
            continue
        link = e.get("link", "")
        summary = clean_text(e.get("summary", "") or e.get("description", ""))
        tp = e.get("published_parsed") or e.get("updated_parsed")
        ts = None
        if tp:
            try:
                ts = datetime.datetime(*tp[:6], tzinfo=datetime.timezone.utc)
            except Exception:
                ts = None
        out.append({
            "title": title,
            "link": link,
            "summary": summary,
            "ts": ts,
            "source": src or "RSS",
        })
    print(f"  + {len(out):3d} from {url}")
    return out


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def collect(feeds):
    items = []
    for u in feeds:
        items += fetch_feed(u)
    # drop stale
    fresh = []
    for it in items:
        if it["ts"] is None:
            fresh.append(it)
        elif (NOW - it["ts"]).total_seconds() <= MAX_AGE_HOURS * 3600:
            fresh.append(it)
    # dedupe by normalized title, keep the one with a timestamp / longer summary
    seen = {}
    for it in fresh:
        k = norm_title(it["title"])
        if not k:
            continue
        if k not in seen:
            seen[k] = it
        else:
            cur = seen[k]
            if (it["ts"] and not cur["ts"]) or (len(it["summary"]) > len(cur["summary"])):
                seen[k] = it
    uniq = list(seen.values())
    # newest first; undated sink to the bottom
    uniq.sort(key=lambda x: x["ts"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc), reverse=True)
    return uniq[:PER_LANE]


# ------------------------------------------------------------------ drafting
def extract_json(text):
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def gemini_draft(item):
    prompt = "\n".join([
        f"You are a senior social copywriter for {BRAND}. {BRAND_CONTEXT}",
        "Write posts that ride the finance news below in the brand's voice: sharp, "
        "confident, plain English, useful to everyday Indian users and savers. Timely "
        "and on-brand, never overclaiming. No investment advice, no return or price "
        "promises, nothing defamatory, no invented numbers beyond the story.",
        "",
        "NEWS STORY",
        f"Headline: {item['title']}",
        f"Source: {item['source']}",
        f"Summary: {item['summary'][:700]}",
        "",
        "Write two posts:",
        "1) X (Twitter): under 260 characters, strong first-line hook, at most 2 hashtags.",
        "2) Instagram caption: 3-5 short lines (hook, context, light CTA), then 4-6 hashtags on the last line.",
        "",
        'Reply with ONLY a JSON object, no markdown: {"x":"...","instagram":"..."}',
    ])
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 700},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    obj = extract_json(text)
    if not obj or "x" not in obj or "instagram" not in obj:
        raise ValueError("unparseable model reply")
    return {"x": str(obj["x"]).strip(), "instagram": str(obj["instagram"]).strip()}


def template_draft(item):
    h = item["title"]
    x = f"{h}\n\nStay on top of your money with {BRAND}. #finance #{BRAND}"
    ig = (f"{h}\n\nWhat it means for you: keep an eye on your money moves.\n\n"
          f"Payments, bills, recharges & more — sorted on {BRAND}.\n\n"
          f"#finance #india #money #markets #{BRAND.lower()}")
    return {"x": x[:260], "instagram": ig}


def draft(item):
    if GEMINI_API_KEY:
        try:
            return gemini_draft(item)
        except Exception as e:
            print(f"    (draft fell back to template: {e})")
    return template_draft(item)


# ------------------------------------------------------------------ render
def fmt_time(ts):
    if not ts:
        return ""
    return ts.astimezone(IST).strftime("%d %b, %I:%M %p")


def esc(s):
    return html.escape(s or "")


def render_card(item, posts):
    src = esc(item["source"])
    when = fmt_time(item["ts"])
    meta = src + (f" &middot; {when} IST" if when else "")
    link = (f'&middot; <a href="{esc(item["link"])}" target="_blank" rel="noopener">open</a>'
            if item["link"] else "")
    x = esc(posts["x"])
    ig = esc(posts["instagram"])
    return f"""
    <div class="card">
      <div class="hd">{esc(item['title'])}</div>
      <div class="src">{meta} {link}</div>
      <div class="post">
        <div class="plabel">X (Twitter) <button class="copy" data-copy="{x}">Copy</button></div>
        <pre class="ptext">{x}</pre>
      </div>
      <div class="post">
        <div class="plabel">Instagram <button class="copy" data-copy="{ig}">Copy</button></div>
        <pre class="ptext">{ig}</pre>
      </div>
    </div>"""


def render_lane(items):
    if not items:
        return '<div class="lanestate">No stories today. The next daily build will refresh this.</div>'
    return "".join(render_card(it, draft(it)) for it in items)


PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<title>{BRAND} Finance Desk</title>
<style>
:root{{--bg:#000;--fg:#f2f2f2;--dim:#8a8a8a;--line:#242424;--line2:#333;--card:#0b0b0b;
  box-sizing:border-box;padding-top:env(safe-area-inset-top,0);padding-bottom:env(safe-area-inset-bottom,0)}}
*{{box-sizing:border-box}} html,body{{margin:0;background:var(--bg)}}
body{{color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased;padding:0 16px 48px}}
a{{color:inherit}} .wrap{{max-width:1100px;margin:0 auto}}
header{{border-bottom:1px solid var(--line);padding:18px 0 12px;margin-bottom:4px}}
h1{{font-size:19px;font-weight:600;margin:0}} h1 .sub{{color:var(--dim);font-weight:400}}
.meta{{color:var(--dim);font-size:12.5px;margin-top:5px}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:16px}}
@media (max-width:760px){{.cols{{grid-template-columns:1fr;gap:26px}}}}
.col h2{{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);font-weight:600;
  margin:0 0 10px;padding-bottom:8px;border-bottom:1px solid var(--line)}}
.lanestate{{color:var(--dim);font-size:13px;padding:8px 0}}
.card{{border:1px solid var(--line);border-radius:3px;background:var(--card);padding:13px 14px;margin-bottom:14px}}
.card .hd{{font-size:15px;font-weight:600;line-height:1.35}}
.card .src{{color:var(--dim);font-size:12px;margin-top:5px}}
.card .src a{{color:var(--dim);text-decoration:underline;text-underline-offset:2px}}
.post{{margin-top:11px;border-top:1px dashed var(--line2);padding-top:9px}}
.plabel{{display:flex;justify-content:space-between;align-items:center;font-size:11px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--dim);margin-bottom:5px}}
.ptext{{white-space:pre-wrap;font:13.5px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  margin:0;color:#e6e6e6}}
button.copy{{font:inherit;font-size:11px;letter-spacing:normal;text-transform:none;color:var(--fg);
  background:transparent;border:1px solid var(--line2);border-radius:2px;padding:3px 9px;cursor:pointer}}
button.copy:hover{{background:#fff;color:#000;border-color:#fff}}
.footer{{color:var(--dim);font-size:11.5px;margin-top:34px;border-top:1px solid var(--line);padding-top:12px}}
</style></head><body><div class="wrap">
<header>
  <h1>{BRAND} Finance Desk <span class="sub">&middot; daily brief</span></h1>
  <div class="meta">India &amp; global finance news with ready-to-post X and Instagram drafts. Rebuilt {built} IST.</div>
</header>
<div class="cols">
  <div class="col"><h2>India</h2>{india}</div>
  <div class="col"><h2>Global</h2>{globl}</div>
</div>
<div class="footer">Auto-generated daily from public RSS feeds. Drafts are starting points &mdash; review before publishing.</div>
</div>
<script>
document.addEventListener('click',function(e){{
  var b=e.target.closest('button.copy'); if(!b) return;
  var t=b.getAttribute('data-copy')||'';
  var done=function(){{var o=b.textContent;b.textContent='Copied';setTimeout(function(){{b.textContent=o}},1200)}};
  if(navigator.clipboard&&navigator.clipboard.writeText){{navigator.clipboard.writeText(t).then(done,done)}}
  else{{var ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();
    try{{document.execCommand('copy')}}catch(_){{}} document.body.removeChild(ta);done()}}
}});
</script>
</body></html>"""


def main():
    print("India feeds:")
    india = collect(INDIA_FEEDS)
    print("Global feeds:")
    globl = collect(GLOBAL_FEEDS)
    print(f"Drafting {len(india)} India + {len(globl)} global stories "
          f"({'Gemini' if GEMINI_API_KEY else 'template fallback'})...")

    page = PAGE.format(
        BRAND=BRAND,
        built=NOW.astimezone(IST).strftime("%d %b %Y, %I:%M %p"),
        india=render_lane(india),
        globl=render_lane(globl),
    )
    os.makedirs("public", exist_ok=True)
    with open("public/index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print("Wrote public/index.html")


if __name__ == "__main__":
    main()
