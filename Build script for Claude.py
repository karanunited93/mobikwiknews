#!/usr/bin/env python3
"""
MobiKwik Finance Desk — static daily builder.

Pulls India + global finance news from public RSS feeds and, per story,
pre-writes social copy in two formats (static post / reel script) and four
tones (formal / informative / comedy / puns), plus suggested hashtags. Writes a
self-contained blue-and-white page to public/index.html. Runs daily in GitHub
Actions (and on demand).

Drafting uses Google's Gemini free tier if GEMINI_API_KEY is set; otherwise it
falls back to simple templates so the page still builds with zero cost.
"""

import os
import re
import html
import json
import time
import datetime
import urllib.request

import feedparser

# ------------------------------------------------------------------ config
BRAND = "MobiKwik"
BRAND_CONTEXT = (
    "MobiKwik is a major Indian fintech app: UPI payments, wallet, bill "
    "payments & recharges, ZIP pay-later, and Xtra investing."
)
BLUE = "#0A4BFF"   # MobiKwik brand blue

INDIA_FEEDS = [
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.livemint.com/rss/markets",
    "https://www.moneycontrol.com/rss/business.xml",
    "https://www.moneycontrol.com/rss/economy.xml",
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://www.financialexpress.com/market/feed/",
]
GLOBAL_FEEDS = [
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",
]

PER_LANE = 8
MAX_AGE_HOURS = 40
TONES = ["formal", "informative", "comedy", "puns"]
TONE_LABEL = {"formal": "Formal", "informative": "Informative",
              "comedy": "Comedy", "puns": "Puns"}

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
NOW = datetime.datetime.now(datetime.timezone.utc)


# ------------------------------------------------------------------ fetch
def clean_text(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


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
        tp = e.get("published_parsed") or e.get("updated_parsed")
        ts = None
        if tp:
            try:
                ts = datetime.datetime(*tp[:6], tzinfo=datetime.timezone.utc)
            except Exception:
                ts = None
        out.append({
            "title": title,
            "link": e.get("link", ""),
            "summary": clean_text(e.get("summary", "") or e.get("description", "")),
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
    fresh = []
    for it in items:
        if it["ts"] is None or (NOW - it["ts"]).total_seconds() <= MAX_AGE_HOURS * 3600:
            fresh.append(it)
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


def gemini_variants(item):
    prompt = "\n".join([
        f"You are a senior social copywriter for {BRAND}. {BRAND_CONTEXT}",
        "From the finance news below, write ready-to-use social content in the "
        "brand's voice: useful to everyday Indian users and savers, timely, "
        "on-brand, never overclaiming. No investment advice, no return or price "
        "promises, nothing defamatory, no invented numbers beyond the story.",
        "",
        "NEWS STORY",
        f"Headline: {item['title']}",
        f"Source: {item['source']}",
        f"Summary: {item['summary'][:600]}",
        "",
        "Produce TWO formats in FOUR tones each:",
        "- Formats: 'static' (a social post = an X post under 260 chars + an "
        "Instagram caption of 3-5 short lines) and 'reel' (a 15-25 second vertical "
        "reel script: a HOOK line, 3-4 short spoken beats with [on-screen text] cues, "
        "then a CTA; plain text with line breaks).",
        "- Tones: formal (professional, precise), informative (clear, explanatory), "
        "comedy (witty and funny but brand-safe), puns (playful wordplay).",
        "Also give 'hashtags': 6-10 relevant tags mixing broad finance/India reach, "
        "topic-specific tags, and 1-2 branded (#MobiKwik), ordered broad to niche.",
        "",
        "Reply with ONLY this JSON, no markdown:",
        '{"static":{"formal":{"x":"","instagram":""},"informative":{"x":"","instagram":""},'
        '"comedy":{"x":"","instagram":""},"puns":{"x":"","instagram":""}},'
        '"reel":{"formal":"","informative":"","comedy":"","puns":""},'
        '"hashtags":["#..."]}',
    ])
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.85, "maxOutputTokens": 2048},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read().decode())
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    obj = extract_json(text)
    if not obj or "static" not in obj or "reel" not in obj:
        raise ValueError("unparseable model reply")
    obj.setdefault("hashtags", [])
    return obj


def template_variants(item):
    h = item["title"]
    tags = ["#Finance", "#India", "#Markets", "#Money", "#Economy", "#MobiKwik"]
    static, reel = {}, {}
    for t in TONES:
        static[t] = {
            "x": f"{h}\n\nHere's what it means for your money. #MobiKwik #Finance"[:260],
            "instagram": (f"{h}\n\nWhat it means for you: keep an eye on your money moves.\n\n"
                          f"Payments, bills & more — sorted on {BRAND}.\n\n" + " ".join(tags)),
        }
        reel[t] = (f"[On screen: {h}]\nHook: Big money news today —\n"
                   f"Beat 1: {h}.\nBeat 2: Here's why it matters for you.\n"
                   f"CTA: Stay money-smart with {BRAND}.")
    return {"static": static, "reel": reel, "hashtags": tags}


def variants_for(item):
    if GEMINI_API_KEY:
        try:
            v = gemini_variants(item)
            time.sleep(1.2)   # stay gentle on the free-tier rate limit
            return v
        except Exception as e:
            print(f"    (fell back to template: {e})")
    return template_variants(item)


# ------------------------------------------------------------------ render
def fmt_time(ts):
    return ts.astimezone(IST).strftime("%d %b, %I:%M %p") if ts else ""


def esc(s):
    return html.escape(s or "")


def render_card(idx, item, v):
    when = fmt_time(item["ts"])
    meta = esc(item["source"]) + (f" &middot; {when} IST" if when else "")
    link = (f' &middot; <a href="{esc(item["link"])}" target="_blank" rel="noopener">source</a>'
            if item["link"] else "")
    tone_btns = "".join(
        f'<button class="pill{" active" if t=="informative" else ""}" data-tone="{t}">{TONE_LABEL[t]}</button>'
        for t in TONES)
    blob = json.dumps(v, ensure_ascii=False).replace("</", "<\\/")
    return f"""
    <article class="card" data-idx="{idx}">
      <h3 class="hd">{esc(item['title'])}</h3>
      <div class="src">{meta}{link}</div>
      <div class="seg">
        <button class="segbtn active" data-format="static">Static post</button>
        <button class="segbtn" data-format="reel">Reel script</button>
      </div>
      <div class="tones">{tone_btns}</div>
      <div class="content"></div>
      <div class="tags"></div>
      <script type="application/json" class="vdata">{blob}</script>
    </article>"""


def render_lane(items):
    if not items:
        return '<div class="empty">No stories today &mdash; the next daily build will refresh this.</div>'
    return "".join(render_card(i, it, variants_for(it)) for i, it in enumerate(items))


PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<title>{BRAND} Finance Desk</title>
<style>
:root{{--blue:{BLUE};--ink:#12141a;--muted:#6b7280;--line:#eceef3;--bg:#ffffff;--soft:#f6f8fc;
  box-sizing:border-box;padding-top:env(safe-area-inset-top,0);padding-bottom:env(safe-area-inset-bottom,0)}}
*{{box-sizing:border-box}} html,body{{margin:0;background:var(--bg)}}
body{{color:var(--ink);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased;padding:0 20px 72px}}
a{{color:var(--blue);text-decoration:none}} a:hover{{text-decoration:underline}}
.wrap{{max-width:1120px;margin:0 auto}}
header{{padding:40px 0 8px}}
h1{{font-size:26px;font-weight:700;letter-spacing:-.02em;margin:0;color:var(--blue)}}
h1 .dot{{color:var(--ink);font-weight:400}}
.tag{{color:var(--muted);font-size:13px;margin-top:8px}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:56px;margin-top:40px}}
@media (max-width:820px){{.cols{{grid-template-columns:1fr;gap:44px}}}}
.col h2{{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--blue);font-weight:700;margin:0 0 20px}}
.empty{{color:var(--muted);font-size:14px}}
.card{{padding:0 0 30px;margin-bottom:30px;border-bottom:1px solid var(--line)}}
.card:last-child{{border-bottom:none}}
.hd{{font-size:19px;line-height:1.34;font-weight:650;margin:0 0 8px;letter-spacing:-.01em}}
.src{{color:var(--muted);font-size:13px;margin-bottom:16px}}
.seg{{display:inline-flex;border:1px solid var(--line);border-radius:999px;padding:3px;margin:0 0 12px;background:var(--soft)}}
.segbtn{{font:inherit;font-size:13px;font-weight:600;color:var(--muted);background:transparent;border:0;
  padding:6px 16px;border-radius:999px;cursor:pointer}}
.segbtn.active{{background:var(--blue);color:#fff}}
.tones{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}}
.pill{{font:inherit;font-size:12.5px;font-weight:600;color:var(--muted);background:#fff;border:1px solid var(--line);
  padding:5px 13px;border-radius:999px;cursor:pointer}}
.pill.active{{color:var(--blue);border-color:var(--blue);background:#eef3ff}}
.block{{margin-bottom:16px}}
.blabel{{display:flex;justify-content:space-between;align-items:center;font-size:11px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted);margin-bottom:7px}}
.btext{{white-space:pre-wrap;font-size:15px;line-height:1.62;margin:0;color:var(--ink)}}
.copy{{font:inherit;font-size:11px;letter-spacing:normal;text-transform:none;color:var(--blue);background:#fff;
  border:1px solid var(--line);border-radius:999px;padding:3px 12px;cursor:pointer}}
.copy:hover{{background:var(--blue);color:#fff;border-color:var(--blue)}}
.tags{{margin-top:6px}}
.tagline{{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-bottom:8px}}
.chips{{display:flex;flex-wrap:wrap;gap:7px;align-items:center}}
.chip{{font-size:13px;color:var(--blue);background:#eef3ff;border-radius:999px;padding:3px 11px}}
.footer{{color:var(--muted);font-size:12px;margin-top:56px;border-top:1px solid var(--line);padding-top:16px}}
</style></head><body><div class="wrap">
<header>
  <h1>{BRAND} <span class="dot">Finance Desk</span></h1>
  <div class="tag">India &amp; global finance news with ready-to-use posts &amp; reel scripts. Rebuilt {built} IST.</div>
</header>
<div class="cols">
  <div class="col"><h2>India</h2>{india}</div>
  <div class="col"><h2>Global</h2>{globl}</div>
</div>
<div class="footer">Auto-generated daily from public RSS feeds. Copy is a starting point &mdash; review before publishing. Hashtags are suggestions.</div>
</div>
<script>
function esc(s){{return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}}
function block(label,text){{
  return '<div class="block"><div class="blabel"><span>'+label+'</span>'+
    '<button class="copy" data-copy="'+esc(text).replace(/"/g,'&quot;')+'">Copy</button></div>'+
    '<pre class="btext">'+esc(text)+'</pre></div>';
}}
function renderCard(card){{
  var v=JSON.parse(card.querySelector('.vdata').textContent);
  var fmt=card.dataset.format||'static', tone=card.dataset.tone||'informative';
  var c=card.querySelector('.content'), out='';
  if(fmt==='static'){{
    var s=(v.static&&v.static[tone])||{{}};
    out=block('X (Twitter)',s.x)+block('Instagram caption',s.instagram);
  }} else {{
    out=block('Reel script',(v.reel&&v.reel[tone])||'');
  }}
  c.innerHTML=out;
  var tags=card.querySelector('.tags');
  if(v.hashtags&&v.hashtags.length){{
    var all=v.hashtags.join(' ');
    tags.innerHTML='<div class="tagline">Suggested hashtags <button class="copy" data-copy="'+
      esc(all).replace(/"/g,'&quot;')+'">Copy all</button></div><div class="chips">'+
      v.hashtags.map(function(h){{return '<span class="chip">'+esc(h)+'</span>'}}).join('')+'</div>';
  }}
}}
document.querySelectorAll('.card').forEach(function(card){{
  card.dataset.format='static'; card.dataset.tone='informative';
  card.querySelectorAll('.segbtn').forEach(function(b){{
    b.onclick=function(){{card.dataset.format=b.dataset.format;
      card.querySelectorAll('.segbtn').forEach(function(x){{x.classList.toggle('active',x===b)}});renderCard(card);}};
  }});
  card.querySelectorAll('.pill').forEach(function(b){{
    b.onclick=function(){{card.dataset.tone=b.dataset.tone;
      card.querySelectorAll('.pill').forEach(function(x){{x.classList.toggle('active',x===b)}});renderCard(card);}};
  }});
  renderCard(card);
}});
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
        BRAND=BRAND, BLUE=BLUE,
        built=NOW.astimezone(IST).strftime("%d %b %Y, %I:%M %p"),
        india=render_lane(india), globl=render_lane(globl),
    )
    os.makedirs("public", exist_ok=True)
    with open("public/index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print("Wrote public/index.html")


if __name__ == "__main__":
    main()
