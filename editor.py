"""editor.py — locked-style auto editor (MoviePy + ffmpeg + PIL).

LOCKED STYLE (encoded exactly):
- 16:9 canvas 1920x1080.
- 9:16 photos: foreground pillar 608x1080, full height, centered;
  background = SAME photo at 180% scale + 35px gaussian blur + 85% brightness,
  filling the whole 16:9 frame.
- 16:9 clips/photos: 85% width (1632px), centered on black.
- Animation (linear, 7s cycle, looped for longer holds):
    foreground 100% -> 108% scale, vertical anchor 50% -> 52%
    background 180% -> 190% scale
- Transitions: ONLY 0.4s cross-dissolve. No slides, no swipes.
- Label: bottom-left black bar (70% opacity) + orange left border,
  white text "Show — Year", 0.5s fade-in.
- Structure: 00:00-00:30 = 10 x 3.0s clip montage; afterwards photos with
  one 3.0s muted exact-show clip every 2 minutes.
- Audio: the user's voice MP3, full length. No music. No watermark.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

from moviepy import (ImageClip, VideoFileClip, AudioFileClip,
                     CompositeVideoClip, ColorClip)
from moviepy.video.fx import CrossFadeIn, FadeIn

import config as C


# ---------------------------------------------------------------- helpers

def load_font(size):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _cycle(t):
    return (t % C.ZOOM_CYCLE) / C.ZOOM_CYCLE


# ---------------------------------------------------------------- layers

def bg_clip(photo_path, dur):
    """Same photo, 180%->190% zoom, blurred 35px, 85% brightness, full 16:9."""
    img = Image.open(photo_path).convert("RGB")
    img = img.filter(ImageFilter.GaussianBlur(C.BLUR_PX))
    img = ImageEnhance.Brightness(img).enhance(C.BG_BRIGHTNESS)
    iw, ih = img.size
    cover = max(C.W / iw, C.H / ih)

    def scale(t):
        c = _cycle(t)
        return cover * (C.BG_ZOOM[0] + (C.BG_ZOOM[1] - C.BG_ZOOM[0]) * c)

    return (ImageClip(np.array(img)).with_duration(dur)
            .resized(scale).with_position(("center", "center")))


def fg_clip(photo_path, dur, phase=0.0):
    """9:16 pillar 608x1080, 100%->108% zoom, vertical anchor 50%->52%."""
    img = Image.open(photo_path).convert("RGB")
    iw, ih = img.size
    cover = max(C.FG_W / iw, C.FG_H / ih)

    def scale(t):
        c = ((t + phase) % C.ZOOM_CYCLE) / C.ZOOM_CYCLE
        return cover * (C.FG_ZOOM[0] + (C.FG_ZOOM[1] - C.FG_ZOOM[0]) * c)

    def pos(t):
        s = scale(t)
        fw, fh = iw * s, ih * s
        c = ((t + phase) % C.ZOOM_CYCLE) / C.ZOOM_CYCLE
        yf = C.Y_DRIFT[0] + (C.Y_DRIFT[1] - C.Y_DRIFT[0]) * c
        return ((C.W - fw) / 2, (C.H - fh) * yf)

    return (ImageClip(str(photo_path)).with_duration(dur)
            .resized(scale).with_position(pos))


def label_clip(show, year, dur):
    """Bottom-left black bar 70% + orange left border + white 'Show — Year'."""
    text = " — ".join([p for p in (show, year) if p])
    if not text:
        return None
    font = load_font(C.LABEL_FONT_SIZE)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    tw = probe.textlength(text, font=font)
    pad, bh, border = 30, 100, 10
    bw = int(tw + pad * 2 + border)
    bar = Image.new("RGBA", (bw, bh), (0, 0, 0, int(255 * C.LABEL_OPACITY)))
    d = ImageDraw.Draw(bar)
    d.rectangle([0, 0, border, bh], fill=C.LABEL_ORANGE + (255,))
    d.text((border + pad, (bh - 62) // 2), text, font=font,
           fill=(255, 255, 255, 255))
    return (ImageClip(np.array(bar)).with_duration(dur)
            .with_effects([FadeIn(C.LABEL_FADE)])
            .with_position((40, C.H - 40 - bh)))


def photo_segment(photo_path, show, year, dur, phase=0.0):
    layers = [bg_clip(photo_path, dur), fg_clip(photo_path, dur, phase)]
    lab = label_clip(show, year, dur)
    if lab:
        layers.append(lab)
    return CompositeVideoClip(layers, size=(C.W, C.H)).with_duration(dur)


def fallback_segment(show, year, dur):
    """Last resort when no photo was found: dark frame + label. Never stock."""
    layers = [ColorClip((C.W, C.H), color=(12, 12, 14)).with_duration(dur)]
    lab = label_clip(show, year, dur)
    if lab:
        layers.append(lab)
    return CompositeVideoClip(layers, size=(C.W, C.H)).with_duration(dur)


def clip_segment(clip_path, show, year, dur=C.CLIP_LEN):
    """Exact-show clip: 16:9 at 85% width, centered, muted."""
    v = VideoFileClip(clip_path).without_audio()
    if v.duration > dur:
        v = v.subclipped(0, dur)
    v = (v.with_duration(dur).resized(width=int(C.W * 0.85))
         .with_position(("center", "center")))
    layers = [ColorClip((C.W, C.H), color=(0, 0, 0)).with_duration(dur), v]
    lab = label_clip(show, year, dur)
    if lab:
        layers.append(lab)
    return CompositeVideoClip(layers, size=(C.W, C.H)).with_duration(dur)


# ---------------------------------------------------------------- timeline

def assemble(segments):
    """Join with ONLY 0.4s cross-dissolves (overlapping CrossFadeIn)."""
    placed, start = [], 0.0
    for i, s in enumerate(segments):
        c = s if i == 0 else s.with_effects([CrossFadeIn(C.XFADE)])
        placed.append(c.with_start(start))
        start += s.duration - (C.XFADE if i < len(segments) - 1 else 0)
    return CompositeVideoClip(placed, size=(C.W, C.H)).with_duration(start)


def distribute(beats, photo_time):
    """Beat durations ~ words/pace, clamped 5-12s, normalized to photo_time."""
    raw = [min(max(b["words"] / C.WPS, C.BEAT_MIN), C.BEAT_MAX) for b in beats]
    s = sum(raw) or 1.0
    return [r / s * photo_time for r in raw]


def render_job(manifest, voice_path, out_path, log_fn=print):
    voice = AudioFileClip(voice_path)
    vdur = voice.duration
    log_fn(f"[editor] voice duration: {vdur:.1f}s")

    beats = manifest["beats"]
    if not beats:
        raise RuntimeError("no beats in manifest — finder found no script entries")

    # ---- montage: 00:00-00:30 = 10 x 3.0s clips (skipped if voice too short)
    montage_n = min(C.MONTAGE_CLIPS, len(manifest["montage_clips"]))
    mont_dur = montage_n * C.CLIP_LEN if vdur > 40 else 0.0
    if mont_dur == 0:
        montage_n = 0
    body_time = max(10.0, vdur - mont_dur)

    # ---- photo/clip mix: one 3.0s clip every 2 minutes of body
    n_inserts = int(body_time // C.CLIP_EVERY_SEC)
    clip_time = n_inserts * C.CLIP_LEN
    photo_time = max(10.0, body_time - clip_time)
    durs = distribute(beats, photo_time)

    photo_pool = {e["person"]: (e["photos"] or []) for e in manifest["entries"]}
    clip_pool = manifest["montage_clips"] or []
    use_idx, ci = {}, 0

    segments, acc, ins_done = [], 0.0, 0
    for bi, (b, d) in enumerate(zip(beats, durs)):
        ph = photo_pool.get(b["person"]) or []
        if ph:
            k = use_idx.get(b["person"], 0)
            use_idx[b["person"]] = k + 1
            # phase offset per repeat so a recycled photo starts mid-zoom
            seg = photo_segment(ph[k % len(ph)], b["show"], b["year"], d,
                                phase=(k * 2.3) % C.ZOOM_CYCLE)
        else:
            log_fn(f"[editor] WARNING: no photo for '{b['person']}' — dark frame used")
            seg = fallback_segment(b["show"], b["year"], d)
        segments.append(seg)
        acc += d
        while (ins_done < n_inserts and clip_pool
               and (ins_done + 1) * C.CLIP_EVERY_SEC <= acc):
            c = clip_pool[ci % len(clip_pool)]
            ci += 1
            segments.append(clip_segment(c["path"], c["show"], c["year"]))
            acc += C.CLIP_LEN
            ins_done += 1

    mont = [clip_segment(m["path"], m["show"], m["year"])
            for m in manifest["montage_clips"][:montage_n]]
    all_segs = mont + segments
    video = assemble(all_segs)
    if video.duration > vdur:
        video = video.with_duration(vdur)
    final = video.with_audio(voice.with_duration(video.duration))

    log_fn(f"[editor] rendering {video.duration:.1f}s "
           f"({len(all_segs)} segments) -> {out_path}")
    final.write_videofile(str(out_path), fps=24, codec="libx264",
                          audio_codec="aac", preset="medium", threads=4,
                          logger=None)
    for c in all_segs:
        c.close()
    voice.close()
    log_fn(f"[editor] done: {out_path}")
    return str(out_path)


# ---------------------------------------------------------------- smoke test (no network)

def smoke():
    tmp = Path("/tmp/vf_smoke")
    tmp.mkdir(exist_ok=True)
    for i, col in enumerate([(180, 40, 40), (40, 90, 180)]):
        Image.new("RGB", (900, 1200), col).save(tmp / f"p{i}.jpg")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=8", "-acodec", "libmp3lame",
                    str(tmp / "v.mp3")],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=True)
    man = {
        "entries": [{"person": "Test Star", "show": "Test Show", "year": "1990",
                     "photos": [str(tmp / "p0.jpg"), str(tmp / "p1.jpg")]}],
        "beats": [{"person": "Test Star", "show": "Test Show", "year": "1990",
                   "words": 20},
                  {"person": "Test Star", "show": "Test Show", "year": "1990",
                   "words": 16}],
        "montage_clips": [],
    }
    out = render_job(man, str(tmp / "v.mp3"), str(tmp / "smoke.mp4"))
    print("SMOKE OK:", out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    if a.smoke:
        smoke()
    else:
        sys.exit("use --smoke for the synthetic pipeline test")
