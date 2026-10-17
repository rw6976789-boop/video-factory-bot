# Video Factory — Web App

**Script + Voice in → locked-style edited video out.** No Telegram needed.

Upload your countdown script (.txt/.md) and voiceover (mp3/wav/m4a) in the browser, and the factory edits the full video in the locked countdown style:

- 1920x1080, 24fps
- 9:16 photos as full-height pillars on the same photo blurred behind (180%->190% bg zoom, 100%->108% fg zoom, 7s linear cycle)
- ONLY 0.4s cross-dissolves on every cut
- Bottom-left "Show — Year" label (black bar 70% + orange border)
- Real 3.0s muted clips from the exact show (montage intro + 1 every 2 min)
- Your voice as the full audio — no music, no watermark, no stock ever

## Pipeline

app.py (Streamlit UI) -> brain.py (Gemini: entry parsing + photo screening) -> finder.py (Wikimedia Commons photos, yt-dlp 3.0s clips) -> editor.py (locked-style render) -> MP4 download in the browser.

## Deploy (Streamlit Community Cloud — free)

1. Go to share.streamlit.io -> New app
2. Select this repo (video-factory-bot), branch main, file app.py -> Deploy
3. (Optional) App settings -> Secrets, add: GEMINI_API_KEY = "your-key". Without a key the factory still works in heuristic mode, but Gemini photo screening and smart entry parsing are skipped.
4. Open the app URL, upload script + voice, hit Render video, download.

packages.txt installs ffmpeg on the host automatically.

## Run locally

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
GEMINI_API_KEY=your-key streamlit run app.py

## Honest limits

- Long renders are slow on free hosting. A 30-min countdown can take 30-60+ min on Streamlit's free tier. Test with a short script first.
- Clips may be skipped on datacenter IPs. YouTube rate-limits yt-dlp from cloud servers (HTTP 429) — photos still come through Wikimedia Commons.
- Keep the browser tab open while rendering.

## Files

- app.py — Streamlit web UI (the active interface)
- brain.py — Gemini brain: parse_script() + check_if_stock() vision QA
- finder.py — visual sourcing (Commons photos, yt-dlp clips, visuals.csv)
- editor.py — locked-style renderer (MoviePy + ffmpeg + PIL)
- config.py — all settings via env vars, never hardcoded secrets
- bot.py / delivery.py / render.yaml / Dockerfile — retired Telegram path, kept for reference only
