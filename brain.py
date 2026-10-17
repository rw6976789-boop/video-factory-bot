"""brain.py — Gemini-powered planning + visual QA for the Video Factory.

- parse_script(script_text) -> JSON list of
  {person, show, year, google_search_keyword, youtube_search_keyword}
- check_if_stock(image_path) -> "APPROVE" | "REJECT" (Gemini vision)

The key is read from env GEMINI_API_KEY — never hardcoded here, because this
repo is pushed to GitHub for deploy and a hardcoded key would leak publicly.
Model via env GEMINI_MODEL (default gemini-3-flash-preview; the
'gemini-2.0-flash' name is retired).
"""
import json
import logging
import os
import re
import time
from pathlib import Path

import config as C

log = logging.getLogger("brain")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# httpx (used by the google-genai SDK) crashes on bracketed IPv6 entries
# like [::1] in no_proxy — sanitize before creating the client.
for _k in ("no_proxy", "NO_PROXY"):
    _v = os.environ.get(_k)
    if _v and "[" in _v:
        os.environ[_k] = ",".join(p for p in _v.split(",") if "[" not in p)

_client_instance = None


def _client():
    global _client_instance
    if _client_instance is None:
        if not C.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY env var is missing.")
        from google import genai
        _client_instance = genai.Client(api_key=C.GEMINI_API_KEY)
    return _client_instance


def _call(prompt, image_path=None, retries=2):
    """Generate with backoff. 429 -> 90s, 503 -> 45s (free-tier flapping)."""
    from google.genai import types
    contents = [prompt]
    if image_path:
        with open(image_path, "rb") as f:
            contents.append(types.Part.from_bytes(
                data=f.read(), mime_type="image/jpeg"))
    last = None
    for attempt in range(retries + 1):
        try:
            resp = _client().models.generate_content(
                model=C.GEMINI_MODEL, contents=contents)
            return (resp.text or "").strip()
        except Exception as e:  # noqa: BLE001
            last, msg = e, str(e)
            wait = 90 if "429" in msg else (45 if "503" in msg else 5)
            log.warning("gemini failed (try %d/%d): %.120s — wait %ds",
                        attempt + 1, retries + 1, msg, wait)
            time.sleep(wait)
    raise RuntimeError(f"Gemini failed after {retries + 1} tries: {last}")


PARSE_PROMPT = """You are parsing a YouTube countdown script (entries like
"Number 14, Paul Lynde ..."). Split it into its entries and return ONLY a
JSON list (no markdown, no commentary) with one object per entry:
[{"person": "<star name>", "show": "<TV show name or ''>",
  "year": "<year or ''>",
  "google_search_keyword": "<person> <show> TV still",
  "youtube_search_keyword": "<show> <person> scene"}]
Rules: person = the star's real name only. show = the classic TV show they
are known for (use the script; '' if unclear). Keep every entry, in order.

SCRIPT:
"""


def parse_script(script_text):
    raw = _call(PARSE_PROMPT + (script_text or "")[:15000])
    m = re.search(r'\\[.*\\]', raw, re.S)
    if not m:
        raise RuntimeError("Gemini did not return a JSON list.")
    items = json.loads(m.group(0))
    out = []
    for it in items:
        person = (it.get("person") or "").strip()
        if not person:
            continue
        out.append({
            "person": person,
            "show": (it.get("show") or "").strip(),
            "year": (it.get("year") or "").strip(),
            "google_search_keyword": (it.get("google_search_keyword")
                                      or f"{person} TV still").strip(),
            "youtube_search_keyword": (it.get("youtube_search_keyword")
                                       or f"{person} scene").strip(),
        })
    log.info("brain parsed %d entries", len(out))
    return out


STOCK_PROMPT = (
    "Is this a real TV show still or frame (actor in character, on-set, "
    "episode scene) — or a generic stock photo / unrelated person / unusable "
    "image? Answer with exactly one word: APPROVE if it is a real TV show "
    "still, REJECT otherwise."
)


def check_if_stock(image_path):
    """APPROVE = real show still, keep it. REJECT = stock/unusable, drop it."""
    try:
        ans = _call(STOCK_PROMPT, image_path=str(image_path)).upper()
    except Exception as e:  # noqa: BLE001
        # Fail open: a vision outage must not block the whole pipeline.
        log.warning("vision check failed for %s (%.80s) — keeping image",
                    Path(image_path).name, e)
        return "APPROVE"
    verdict = "APPROVE" if "APPROVE" in ans else "REJECT"
    log.info("vision %s: %s", verdict, Path(image_path).name)
    return verdict
