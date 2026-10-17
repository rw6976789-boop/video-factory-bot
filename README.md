# Video Factory Bot — YouTube Auto Video Factory Agent

Send **Script + Voice** on Telegram → get back a finished video in your
**LOCKED STYLE**. No watermark, no music, human-paced editing.

## What it does

1. **bot.py** — listens on Telegram for your script (text / .txt) + voice
   (voice note / audio / MP3). When both arrive, the pipeline runs and the
   finished MP4 comes back in the same chat.
2. **brain.py** — Gemini brain (vision-capable):
   - `parse_script()` → JSON plan per entry:
     `{person, show, year, google_search_keyword, youtube_search_keyword}`
   - `check_if_stock()` → every downloaded photo is shown to Gemini Vision:
     `APPROVE` = real TV still (kept), `REJECT` = stock/unusable (deleted,
     next candidate tried). Fails open on vision outages so one API
     hiccup never blocks a video.
3. **finder.py** — takes the brain's JSON, downloads 9:16 HD photos per
   `google_search_keyword` (Commons → Google CSE fallback), cuts 3.0s
   muted clips per `youtube_search_keyword` via `yt-dlp --download-sections`
   (exact-show query only). Writes `visuals.csv` + `mapping.csv`.
   **No stock, ever.** If the key/brain is down, heuristic parsing keeps
   the factory running (without vision QA).
3. **editor.py** — locked-style render (MoviePy + ffmpeg + PIL):
   - 1920×1080 canvas; 9:16 photos as full-height 608×1080 pillar, centered;
     background = same photo @180% + 35px blur + 85% brightness.
   - 16:9 clips/photos at 85% width, centered.
   - Linear 7s zoom loop: foreground 100%→108% (anchor 50%→52%),
     background 180%→190%. Recycled photos restart mid-zoom so repeats
     look different (anti-loop).
   - ONLY 0.4s cross-dissolve transitions. No slides/swipes.
   - Bottom-left label: black bar 70% + orange left border, white
     "Show — Year", 0.5s fade-in.
   - 00:00–00:30 = 10×3s clip montage; then photos with one 3s clip
     every 2 minutes. Your voice MP3 = full audio. No music, no watermark.
   - Beat timing follows your narration (~140 wpm): one photo hold per
     sentence, 5–12s each.
4. **delivery.py** — ≤50MB goes straight to Telegram; >50MB uploads to
   Google Drive (service account) and sends you the link.

## Setup (your 3 steps — about 10 minutes)

### 1. Create the bot (2 min, in YOUR Telegram app — only you can do this)
1. Open Telegram → search `@BotFather` → `/newbot`
2. Name it (e.g. `MyChannelName Video Factory Bot`), pick a username
   ending in `bot`
3. BotFather gives you the **token** — copy it, keep it private

### 2. Deploy (one click)
**Render.com** (recommended):
1. Push this folder to a GitHub repo
2. Render → New → Blueprint → select the repo (`render.yaml` is included)
3. Add env var `TELEGRAM_BOT_TOKEN` = your token → Deploy
4. The worker stays online 24/7 (needs a paid instance ~$7/mo for
   always-on; free tier sleeps)

**Railway** (alternative): New Project → Deploy from repo → add the same
env var. Same Dockerfile works.

### 3. Use it
Open your bot → `/start` → send script text → send voice → wait for the
video back in chat. `/cancel` resets.

## Optional env vars

| Var | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | **required** — from BotFather |
| `GEMINI_API_KEY` | **required for the brain** — your Gemini key (env only, never in code) |
| `GEMINI_MODEL` | optional — default `gemini-3-flash-preview` (`gemini-2.0-flash` is retired) |
| `GOOGLE_API_KEY` / `GOOGLE_CX` | photo fallback if Commons is thin |
| `GDRIVE_SA_JSON` | path to service-account JSON (only for >50MB videos) |
| `GDRIVE_FOLDER_ID` | Drive folder for big uploads |
| `DATA_DIR` | working dir (default `/data`) |

Tip: drop a `cast.csv` (`person,show,year` header) next to the job to
override show/year detection for tricky scripts.

## Honest limitations

- **YouTube/yt-dlp:** downloading clips from YouTube violates YouTube's ToS
  and can rate-limit datacenter IPs (429s). The code retries and skips
  gracefully, but run it on Render/Railway (residential-ish egress), not
  from a blocked IP. Short 3s muted clips are your fair-use call.
- **Render free tier sleeps** — 24/7 needs the paid worker tier.
- **Telegram Bot API file cap is 50MB** — bigger videos need the Drive
  service account, or split the script into two parts.
- **Render is not instant:** a 35-min video takes a while to render
  (CPU-bound ken-burns). The bot sends progress updates.
- Show/year detection is heuristic — check `mapping.csv` in the job
  folder for the first runs and add `cast.csv` overrides where needed.
