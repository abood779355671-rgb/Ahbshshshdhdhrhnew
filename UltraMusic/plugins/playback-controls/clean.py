# ==============================================================================
# clean.py - Clean Temporary Files Command
# ==============================================================================
# Deletes unused temporary files from downloads/ and cache/ directories.
# Files currently being streamed or waiting in the queue are protected.
#
# Commands:
#   /تنظيف  →  Admin only — scan and remove stale temp files
#   /clean   →  English alias
#
# Safety logic:
#   - Reads queue.queues for ALL active chats
#   - Extracts every file_path from Media/Track objects
#   - Builds a protected set → only deletes files NOT in that set
#   - Reports count + freed space
# ==============================================================================

import glob
import os

from pyrogram import filters
from pyrogram.errors import ChatSendPlainForbidden, ChatWriteForbidden
from pyrogram.types import Message

from UltraMusic import app, lang, queue
from UltraMusic.helpers import admin_check, command


# ── Helpers ────────────────────────────────────────────────────────────────────

def _collect_active_files() -> set[str]:
    """
    Return a set of normalised paths for every file currently
    in any chat queue (playing or waiting).
    """
    protected: set[str] = set()
    for chat_id in list(queue.queues.keys()):
        for track in list(queue.queues[chat_id]):
            fp = getattr(track, "file_path", None)
            if fp and isinstance(fp, str):
                protected.add(os.path.normpath(fp))
    return protected


def _human_size(num_bytes: int) -> str:
    """Convert bytes → human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


# ── Command handler ─────────────────────────────────────────────────────────────

@app.on_message(
    command(["تنظيف", "clean"]) & filters.group & ~app.bl_users
)
@lang.language()
@admin_check
async def clean_temp_files(_, m: Message):
    """
    Scan downloads/ and cache/ for stale files and delete them.
    Files referenced by any active queue entry are left untouched.
    """
    # Auto-delete the command message
    try:
        await m.delete()
    except Exception:
        pass

    # Tell the user we're working
    status = await m.reply_text(m.lang["clean_scanning"])

    # Build the protected set (files currently in use)
    active_files = _collect_active_files()

    deleted_count: int = 0
    freed_bytes: int = 0
    error_count: int = 0

    # Patterns to scan — covers every extension yt-dlp / ffmpeg may produce
    scan_patterns = [
        "downloads/*.mp4",
        "downloads/*.m4a",
        "downloads/*.webm",
        "downloads/*.opus",
        "downloads/*.mp3",
        "downloads/*.ogg",
        "downloads/*.wav",
        "downloads/*.raw",
        "downloads/*.part",   # incomplete yt-dlp downloads
        "cache/*.jpg",
        "cache/*.jpeg",
        "cache/*.png",
        "cache/*.webp",
    ]

    for pattern in scan_patterns:
        for filepath in glob.glob(pattern):
            norm = os.path.normpath(filepath)

            # Skip files that are in an active queue
            if norm in active_files:
                continue

            try:
                freed_bytes += os.path.getsize(filepath)
                os.remove(filepath)
                deleted_count += 1
            except OSError:
                error_count += 1

    # ── Build reply ──────────────────────────────────────────────────────────
    try:
        if deleted_count == 0 and error_count == 0:
            await status.edit_text(m.lang["clean_no_files"])
        elif deleted_count == 0 and error_count > 0:
            await status.edit_text(m.lang["clean_errors"].format(error_count))
        else:
            text = m.lang["clean_done"].format(
                deleted_count,
                _human_size(freed_bytes),
            )
            if error_count:
                text += m.lang["clean_partial_errors"].format(error_count)
            await status.edit_text(text)
    except (ChatSendPlainForbidden, ChatWriteForbidden):
        pass
