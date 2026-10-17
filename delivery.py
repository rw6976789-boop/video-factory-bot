"""delivery.py — send the finished video back on Telegram.

- <= 50MB: sent straight to chat as a document (keeps full quality).
- > 50MB: uploaded to Google Drive (service account) and the link is sent.
  Needs GDRIVE_SA_JSON env pointing at a service-account JSON file.
"""
import asyncio
import logging
import os
from pathlib import Path

import config as C

log = logging.getLogger("delivery")


def drive_upload(path):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    if not C.GDRIVE_SA_JSON or not Path(C.GDRIVE_SA_JSON).exists():
        raise RuntimeError(
            "Video 50MB se bara hai aur GDRIVE_SA_JSON set nahi — "
            "Drive upload ke liye service-account JSON ka path env mein dein.")
    creds = service_account.Credentials.from_service_account_file(
        C.GDRIVE_SA_JSON,
        scopes=["https://www.googleapis.com/auth/drive.file"])
    svc = build("drive", "v3", credentials=creds)
    meta = {"name": Path(path).name}
    if C.GDRIVE_FOLDER:
        meta["parents"] = [C.GDRIVE_FOLDER]
    media = MediaFileUpload(path, mimetype="video/mp4", resumable=True)
    f = svc.files().create(body=meta, media_body=media,
                           fields="id").execute()
    fid = f["id"]
    svc.permissions().create(fileId=fid,
                             body={"type": "anyone",
                                   "role": "reader"}).execute()
    return f"https://drive.google.com/file/d/{fid}/view"


async def deliver(bot, chat_id, video_path):
    size_mb = os.path.getsize(video_path) / 1e6
    log.info("delivering %s (%.1f MB)", video_path, size_mb)
    if size_mb <= C.TG_MAX_MB:
        with open(video_path, "rb") as fh:
            await bot.send_document(
                chat_id, fh, filename=Path(video_path).name,
                caption="Ho gaya Ustad g ✅ — locked style mein. Download kar lein.")
    else:
        link = await asyncio.to_thread(drive_upload, video_path)
        await bot.send_message(
            chat_id,
            f"Video {size_mb:.0f}MB hai (Telegram limit 50MB) — "
            f"Drive link se download karein:\n{link}")
