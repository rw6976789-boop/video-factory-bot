"""Video Factory Bot — configuration. Everything comes from env vars; no secrets in code."""
import os

DATA_DIR  = os.environ.get("DATA_DIR", "/data")
INCOMING  = os.path.join(DATA_DIR, "incoming")
WORK      = os.path.join(DATA_DIR, "work")
OUTPUT    = os.path.join(DATA_DIR, "output")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# Google Custom Search (optional photo fallback). Wikimedia Commons is the default (no key).
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_CX      = os.environ.get("GOOGLE_CX", "")

# Gemini brain. Read from env — NEVER hardcode: this repo is pushed to
# GitHub for deploy and a hardcoded key would leak publicly.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# 'gemini-2.0-flash' is retired; default is a verified-working flash model.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

# Google Drive (optional, only needed for >50MB deliveries).
GDRIVE_SA_JSON = os.environ.get("GDRIVE_SA_JSON", "")
GDRIVE_FOLDER  = os.environ.get("GDRIVE_FOLDER_ID", "")

# ---------------- Locked style constants ----------------
W, H = 1920, 1080
FG_W, FG_H = 608, 1080            # 9:16 pillar, full height, centered
BG_ZOOM = (1.80, 1.90)            # background zoom over one cycle
FG_ZOOM = (1.00, 1.08)            # foreground zoom over one cycle
Y_DRIFT = (0.50, 0.52)            # vertical anchor drift over one cycle
ZOOM_CYCLE = 7.0                  # seconds, linear
BLUR_PX = 35
BG_BRIGHTNESS = 0.85
XFADE = 0.4                       # cross-dissolve only, seconds
LABEL_FADE = 0.5
LABEL_OPACITY = 0.70
LABEL_ORANGE = (255, 122, 26)
LABEL_FONT_SIZE = 46
CLIP_LEN = 3.0                    # every clip is exactly 3.0s, muted
MONTAGE_CLIPS = 10
MONTAGE_LEN = 30.0                # 00:00-00:30 = 10 x 3s montage
CLIP_EVERY_SEC = 120.0            # after montage: 1 clip every 2 min
PHOTOS_PER_PERSON = 6
BEAT_MIN, BEAT_MAX = 5.0, 12.0    # one photo hold per beat
WPS = 2.33                        # ~140 wpm narration pace
TG_MAX_MB = 50                    # Telegram Bot API file limit

for _d in (INCOMING, WORK, OUTPUT):
    os.makedirs(_d, exist_ok=True)
