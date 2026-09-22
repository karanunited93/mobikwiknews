# MobiKwik Finance Desk (free, no-login public page)

A daily-updating black-and-white page of India + global finance news, each story
with a ready-to-copy X post and Instagram caption. Anyone can open the link — no
Claude, no connector, no signup on the viewer's side.

Everything here is free: GitHub hosting, the daily scheduler, and RSS. The only
optional signup is a **free** Google AI (Gemini) key for better post drafts. With
no key, it still builds using simple template posts.

## What runs
- `build.py` — pulls RSS feeds, dedupes, drafts posts, writes `public/index.html`.
- `.github/workflows/build.yml` — runs `build.py` once a day (08:00 IST) and on demand, then deploys to GitHub Pages.

## Setup (about 10 minutes, all free)

1. **Create a GitHub repo** and upload these files (keep the folder structure, incl. `.github/workflows/build.yml`).

2. **Turn on Pages:** repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.

3. **(Optional but recommended) Add a free Gemini key for better drafts:**
   - Get a key at Google AI Studio (aistudio.google.com) → *Get API key*. The free tier needs no credit card.
   - In the repo: **Settings → Secrets and variables → Actions → New repository secret**, name it `GEMINI_API_KEY`, paste the key.
   - Skip this and the page still builds with template posts.

4. **Run it:** repo **Actions → Build finance desk → Run workflow**. It also runs automatically every morning.

5. **Get your link:** after the run, **Settings → Pages** shows the public URL. Share it with anyone.

## Change anything
- **Model name:** if a Gemini model name ever changes, set a repo **variable** `GEMINI_MODEL` (Settings → Secrets and variables → Actions → Variables). Default is `gemini-2.5-flash`.
- **Feeds / counts / brand:** edit the config block at the top of `build.py` (`INDIA_FEEDS`, `GLOBAL_FEEDS`, `PER_LANE`, `BRAND`).
- **Run time:** change the `cron` line in `build.yml` (it's in UTC; 08:00 IST = `30 2 * * *`).

## Cost
Zero for hosting, scheduling, and RSS. Gemini free tier covers ~16 short drafts a
day comfortably. No paid plan required.
