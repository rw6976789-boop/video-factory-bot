"""Video Factory — web app.

Upload Script + Voice, get the locked-style edited video back.
Same pipeline as the Telegram bot (brain -> finder -> editor),
wrapped in a Streamlit UI. No Telegram account needed.

Deploy: Streamlit Community Cloud -> New app -> this repo, main, app.py.
Secrets (optional): GEMINI_API_KEY — without it the factory still works,
but Gemini photo screening + smart entry parsing are skipped.
"""
import os
import re
import tempfile
import traceback
from pathlib import Path

# config.py creates /data dirs at import time — point it at a writable
# temp dir FIRST (Streamlit Cloud cannot write to /data).
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="vf_data_")

import streamlit as st  # noqa: E402

import config as C  # noqa: E402
import finder  # noqa: E402
import editor  # noqa: E402

st.set_page_config(page_title="Video Factory", page_icon="🎬", layout="centered")
st.title("🎬 Video Factory")
st.caption("Script + Voice in → locked-style edited video out. No Telegram needed.")

# ---------------- sidebar: key ----------------
with st.sidebar:
    st.header("Settings")
    key = ""
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        pass
    typed = st.text_input(
        "Gemini API key (optional)", type="password",
        help="Smarter entry parsing + photo quality screening. "
             "Without it, the factory still runs on heuristics.")
    if typed:
        key = typed
    if key:
        os.environ["GEMINI_API_KEY"] = key
        C.GEMINI_API_KEY = key
        st.success("Gemini key active ✓")
    else:
        st.info("No Gemini key — heuristic mode (photos still screened out "
                "only if key present).")
    fast_mode = st.checkbox(
        "Fast mode (skip Gemini, use heuristic parsing)", value=False,
        help="Use this when Gemini is slow or rate-limited. Photos still "
             "download; only the AI parsing and photo screening are skipped.")
    if fast_mode:
        C.GEMINI_API_KEY = ""
        st.info("Fast mode on — heuristic parsing, no Gemini calls.")
    st.caption("build v6 · brain+photo fixes + fast mode")

# ---------------- inputs ----------------
st.subheader("1. Script")
script_file = st.file_uploader("Upload script (.txt / .md)", type=["txt", "md"])
script_paste = st.text_area("…or paste the script here", height=180)

st.subheader("2. Voiceover")
voice_file = st.file_uploader("Upload voiceover (mp3 / wav / m4a)",
                              type=["mp3", "wav", "m4a"])

st.subheader("3. Render")
out_name = st.text_input("Video file name",
                         value="video-factory-output.mp4")
st.warning("⏳ Long videos take a while — a 30-min countdown can need 30-60+ min "
           "on free hosting. Keep this tab open. Test with a short script first.")

# ---------------- run ----------------
if st.button("🎬 Render video", type="primary"):
    script_text = ""
    if script_file is not None:
        script_text = script_file.read().decode("utf-8", errors="replace")
    elif script_paste.strip():
        script_text = script_paste
    if not script_text.strip():
        st.error("Pehle script upload karein ya paste karein.")
        st.stop()
    if voice_file is None:
        st.error("Voiceover file upload karein.")
        st.stop()

    job = Path(tempfile.mkdtemp(prefix="vfjob_"))
    ext = voice_file.name.rsplit(".", 1)[-1].lower()
    voice_path = job / f"voice.{ext}"
    voice_path.write_bytes(voice_file.getbuffer())

    safe = re.sub(r"[^a-z0-9_.-]+", "-", (out_name or "output.mp4").lower()
                  ).strip("-") or "output.mp4"
    if not safe.endswith(".mp4"):
        safe += ".mp4"
    out_path = job / safe

    logs = st.expander("📋 Render log", expanded=True)
    def log_fn(msg):
        logs.write(msg)

    try:
        with st.status("🎥 Factory running…", expanded=True) as status:
            st.write("**Step 1/3** — Planning entries "
                     f"({'Gemini brain' if C.GEMINI_API_KEY else 'heuristic mode'})…")
            manifest = finder.run(script_text, job)
            n_entries = len(manifest.get("entries", []))
            n_photos = sum(len(e.get("photos", []))
                           for e in manifest.get("entries", []))
            n_clips = len(manifest.get("montage_clips", []))
            st.write(f"Found **{n_entries}** entries, **{n_photos}** photos, "
                     f"**{n_clips}** clips.")
            status.update(label="Step 2/3 — Editing video…")
            st.write("**Step 2/3** — Editing in locked style "
                     "(pillar photos, 0.4s dissolves, 3.0s clips)…")
            editor.render_job(manifest, str(voice_path), str(out_path),
                              log_fn=log_fn)
            status.update(label="Step 3/3 — Done ✓", state="complete")
    except Exception as e:  # noqa: BLE001
        st.error(f"Render failed: {e}")
        logs.code(traceback.format_exc()[-3000:])
        st.stop()

    st.success("✅ Video ready!")
    st.video(str(out_path))
    st.download_button("⬇️ Download MP4", data=out_path.read_bytes(),
                       file_name=safe, mime="video/mp4")
    st.caption(f"Size: {out_path.stat().st_size / 1e6:.1f} MB")
