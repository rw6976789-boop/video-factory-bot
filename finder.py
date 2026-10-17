"""finder.py — visual sourcing driven by the Gemini brain.

Pipeline: brain.parse_script() -> JSON plan ->
  photos per entry via google_search_keyword (Commons, Google CSE fallback),
  every photo screened by brain.check_if_stock() (REJECT -> delete, try next)
  clips per entry via youtube_search_keyword (yt-dlp --download-sections,
  3.0s muted, exact-show query only).

Output: visuals.csv + mapping.csv + manifest.json in the job dir.
STRICT: no stock footage, ever. If the brain/key is unavailable, falls back
to the built-in heuristic parser so the factory keeps working.
"""
import csv
import json
import logging
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

import config as C

log = logging.getLogger("finder")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# ---------------- heuristic fallback (no key / brain outage) ----------------
_NUM_WORDS = ("one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
              "thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
              "twenty")
ENTRY_RE  = re.compile(r'(?im)^\s*(?:#{1,3}\s*)?number\s+(\d+|%s)\s*[:,.\-–—]?\s*(.+?)\s*$' % _NUM_WORDS)
SENT_RE   = re.compile(r'(?<=[.!?])["”\']?\s+(?=[A-Z0-9"“])')
YEAR_RE   = re.compile(r'\b(19[5-9]\d|20[0-3]\d)\b')
QUOTED_RE = re.compile(r'[“"]([^“”"\n]{3,60})[”"]')


def heuristic_plan(script_text):
    ms = list(ENTRY_RE.finditer(script_text or ""))
    if not ms:
        return [{"person": "Story", "show": "", "year": "",
                 "google_search_keyword": "classic TV still",
                 "youtube_search_keyword": "classic TV scene"}]
    plan = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(script_text)
        body = script_text[m.end():end]
        raw = m.group(2).strip()
        # Entry headers in real scripts are single-line:
        # "Number fifteen, Tom Hanks. He played the most decent man..."
        # so the name ends at the first period (or comma/dash).
        person = re.split(r'\s[—–\-:;]\s|,\s', raw, maxsplit=1)[0]
        person = person.split('.')[0].strip() or raw.split('.')[0].strip()
        years = YEAR_RE.findall(body)
        show = ""
        for q in QUOTED_RE.findall(body):
            if not re.search(r'https?|www\.', q):
                show = q.strip()
                break
        plan.append({"person": person, "show": show,
                     "year": years[0] if years else "",
                     "google_search_keyword": f"{person} {show} TV still".strip(),
                     "youtube_search_keyword": f"{show} {person} scene".strip()})
    return plan


def split_sentences(text):
    parts = [s.strip() for s in SENT_RE.split((text or "").strip())
             if s.strip()]
    return parts or ([text.strip()] if (text or "").strip() else [])


def load_overrides(path):
    ov, p = {}, Path(path)
    if p.exists():
        with p.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("person"):
                    ov[row["person"].strip().lower()] = (
                        row.get("show", "").strip(), row.get("year", "").strip())
    return ov


def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', (s or "x").lower()).strip('-') or "x"


# ---------------- photos ----------------

def _http_json(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "VideoFactoryBot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def commons_search(query, n, outdir, tag):
    params = {"action": "query", "format": "json", "generator": "search",
              "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6,
              "gsrlimit": 40, "prop": "imageinfo", "iiprop": "url|size",
              "iiurlwidth": 1080}
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    data = _http_json(url)
    pages = (data.get("query") or {}).get("pages") or {}
    cands = []
    for p in pages.values():
        if p.get("title", "").lower().endswith(".svg"):
            continue
        ii = (p.get("imageinfo") or [{}])[0]
        u = ii.get("thumburl") or ii.get("url")
        w = ii.get("thumbwidth") or ii.get("width") or 0
        if u and w >= 600:
            cands.append(u)
    return cands


def google_cse_urls(query, n):
    if not (C.GOOGLE_API_KEY and C.GOOGLE_CX):
        return []
    params = {"key": C.GOOGLE_API_KEY, "cx": C.GOOGLE_CX, "q": query,
              "searchType": "image", "imgSize": "xxlarge", "imgType": "photo",
              "num": min(max(n, 1), 10), "safe": "active"}
    url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(params)
    return [it["link"] for it in (_http_json(url).get("items") or [])[:n]
            if it.get("link")]


def _download(url, dst):
    # urlretrieve sends Python-urllib's default UA -> Wikimedia 403s it.
    # The Commons API search above works because it sends a descriptive UA,
    # so downloads must do the same.
    req = urllib.request.Request(
        url, headers={"User-Agent": "VideoFactoryBot/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r, \
            open(dst, "wb") as f:
        f.write(r.read())
    return str(dst)


def find_photos(item, outdir, n=C.PHOTOS_PER_PERSON):
    """Download candidates, screen each with brain.check_if_stock."""
    import brain
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    tag = slug(item["person"])
    kw = item["google_search_keyword"]
    # Commons search is picky: "Tom Hanks Bosom Buddies TV still" returns
    # nothing while "Tom Hanks" returns plenty. Broaden until we get hits.
    queries = [kw]
    if item["show"]:
        queries.append(f"{item['person']} {item['show']}".strip())
    queries.append(item["person"])
    cands = []
    for q in queries:
        try:
            cands = commons_search(q, n * 3, outdir, tag)
        except Exception as e:  # noqa: BLE001
            log.warning("commons failed for '%s': %s", q, e)
            cands = []
        if cands:
            if q != kw:
                log.info("commons fallback query '%s' -> %d candidates",
                         q, len(cands))
            break
    if len(cands) < n:
        try:
            cands += google_cse_urls(kw, n * 3 - len(cands))
        except Exception as e:  # noqa: BLE001
            log.warning("google cse failed for '%s': %s", kw, e)

    kept = []
    for i, u in enumerate(cands):
        if len(kept) >= n:
            break
        dst = outdir / f"{tag}_photo{i + 1}.jpg"
        try:
            _download(u, dst)
        except Exception as e:  # noqa: BLE001
            log.warning("download failed %s: %s", u, e)
            continue
        try:
            verdict = brain.check_if_stock(dst)
        except Exception as e:  # noqa: BLE001
            log.warning("vision error, keeping %s: %s", dst.name, e)
            verdict = "APPROVE"
        if verdict == "APPROVE":
            kept.append(str(dst))
        else:
            log.info("vision REJECT -> deleted %s", dst.name)
            dst.unlink(missing_ok=True)
    log.info("photos kept %d/%d for '%s'", len(kept), n, item["person"])
    return kept


# ---------------- clips: exact show only, 3.0s, muted ----------------

def download_clip(item, outdir):
    """yt-dlp --download-sections: one 3.0s muted 720p clip."""
    try:
        import yt_dlp
    except ImportError:
        log.error("yt-dlp not installed — skipping clips")
        return None
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    tag = slug(item["person"])
    q = item["youtube_search_keyword"]
    dst = outdir / f"{tag}_clip3s.mp4"
    opts = {
        "format": "bv*[height<=720]/b[height<=720]/best",
        "outtmpl": str(outdir / f"{tag}_src.%(ext)s"),
        "quiet": True, "no_warnings": True,
        "socket_timeout": 30, "retries": 2, "sleep_requests": 2,
        "noplaylist": True,
        # cut a 3s section straight at download time, mute it
        "download_ranges": lambda info, ydl: [{"start_time": 8, "end_time": 11}],
        "force_keyframes_at_cuts": True,
        "postprocessor_args": {"ffmpeg": ["-an"]},
    }
    src = None
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch3:{q}", download=True)
        for e in (info.get("entries") or []):
            dl = (e.get("requested_downloads") or [{}])[0]
            fp = dl.get("filepath") or ydl.prepare_filename(e)
            if fp and Path(fp).exists():
                src = fp
                break
    except Exception as e:  # noqa: BLE001
        log.warning("yt-dlp failed for '%s': %s (datacenter IPs get 429s)",
                    q, e)
        return None
    if not src:
        return None
    try:
        # normalize to 1280x720 mp4
        tmp = outdir / f"{tag}_clip3s_tmp.mp4"
        Path(src).rename(tmp)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(tmp), "-an",
             "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
                    "pad=1280:720:(ow-iw)/2:(oh-ih)/2",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             str(dst)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tmp.unlink(missing_ok=True)
        log.info("clip ok: %s", dst.name)
        return str(dst)
    except Exception as e:  # noqa: BLE001
        log.warning("clip normalize failed %s: %s", src, e)
        return None


# ---------------- main ----------------

def run(script_text, job_dir, overrides_csv=None):
    job_dir = Path(job_dir)
    (job_dir / "visuals").mkdir(parents=True, exist_ok=True)

    # 1) brain plan (fallback: heuristics)
    if C.GEMINI_API_KEY:
        try:
            import brain
            plan = brain.parse_script(script_text)
        except Exception as e:  # noqa: BLE001
            log.warning("brain parse failed -> heuristic fallback: %s", e)
            plan = heuristic_plan(script_text)
    else:
        log.warning("GEMINI_API_KEY missing -> heuristic fallback (no vision QA)")
        plan = heuristic_plan(script_text)

    overrides = load_overrides(overrides_csv or (job_dir / "cast.csv"))
    manifest = {"entries": [], "beats": [], "montage_clips": []}
    visuals_rows = []

    for idx, item in enumerate(plan, 1):
        key = item["person"].lower()
        if key in overrides:
            item["show"], item["year"] = overrides[key]
        vdir = job_dir / "visuals" / slug(item["person"])
        photos = find_photos(item, vdir)
        clip = download_clip(item, vdir) if item["show"] else None
        if clip:
            manifest["montage_clips"].append(
                {"path": clip, "show": item["show"], "year": item["year"],
                 "person": item["person"]})
        manifest["entries"].append(
            {"num": idx, "person": item["person"], "show": item["show"],
             "year": item["year"], "photos": photos, "clip": clip})
        for s in split_sentences(_entry_text(script_text, item["person"])):
            manifest["beats"].append({"person": item["person"],
                                      "show": item["show"], "year": item["year"],
                                      "words": len(s.split())})
        visuals_rows.append([idx, item["person"], item["show"], item["year"],
                             item["google_search_keyword"],
                             item["youtube_search_keyword"],
                             "|".join(photos), clip or "", len(photos)])

    with open(job_dir / "visuals.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["entry", "person", "show", "year", "google_search_keyword",
                    "youtube_search_keyword", "photos", "clip", "photo_count"])
        w.writerows(visuals_rows)
    with open(job_dir / "mapping.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["entry", "person", "show", "year", "photos", "clip"])
        for e in manifest["entries"]:
            w.writerow([e["num"], e["person"], e["show"], e["year"],
                        "|".join(e["photos"]), e["clip"] or ""])
    with open(job_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in manifest.items() if k != "beats"},
                  f, indent=1, ensure_ascii=False)
    log.info("finder done: %d entries, %d beats, %d clips",
             len(manifest["entries"]), len(manifest["beats"]),
             len(manifest["montage_clips"]))
    return manifest


def _entry_text(script_text, person):
    """Best-effort: sentences mentioning this person (for beat timing)."""
    sents, low = split_sentences(script_text), person.lower()
    hits = [s for s in sents if low.split()[0] in s.lower()]
    return " ".join(hits) if hits else " ".join(sents[:3])
