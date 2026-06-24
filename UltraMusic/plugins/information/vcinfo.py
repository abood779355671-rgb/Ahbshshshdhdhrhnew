# ==============================================================================
# vcinfo.py - Voice Chat Members Info
# ==============================================================================
# Shows all participants currently in the group voice chat, with:
#   • Mute / unmute status  🔇 🎙️
#   • Volume level          🎚️  (0-200)
#   • Screen-share flag     🖥️
#   • Total count
#
# Commands:
#   /vcinfo       →  Admin / auth only
#   /vcmembers    →  Alias
#   /اعضاء_الصوت  →  Arabic alias
#
# How it works:
#   1. db.get_assistant(chat_id)  → returns the PyTgCalls client for this chat
#   2. client.get_participants(chat_id)  → list of GroupCallParticipant
#   3. app.get_users(user_id)     → resolve display name via Bot API
#   4. Format & send (falls back to a .txt file for very large VCs)
# ==============================================================================

import os

from pyrogram import filters
from pyrogram.errors import ChatSendPlainForbidden, ChatWriteForbidden
from pyrogram.types import Message

from UltraMusic import app, db, lang
from UltraMusic.helpers import can_manage_vc, command


# ── Helper ─────────────────────────────────────────────────────────────────────

async def _resolve_name(user_id: int) -> str:
    """
    Try to resolve a display name for a participant.
    Returns a clickable mention if possible, otherwise just the numeric ID.
    """
    try:
        user = await app.get_users(user_id)
        if user.username:
            return f"@{user.username}"
        return f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
    except Exception:
        return f"<code>{user_id}</code>"


# ── Command handler ─────────────────────────────────────────────────────────────

@app.on_message(
    command(["vcinfo", "vcmembers", "اعضاء_الصوت"]) & filters.group & ~app.bl_users
)
@lang.language()
@can_manage_vc
async def vc_info(_, m: Message):
    """
    Fetch and display all participants in the current voice chat.
    """
    # Auto-delete the command message
    try:
        await m.delete()
    except Exception:
        pass

    chat_id = m.chat.id

    # ── Guard: make sure there is an active call ────────────────────────────
    if not await db.get_call(chat_id):
        try:
            return await m.reply_text(m.lang["vcinfo_no_call"])
        except (ChatSendPlainForbidden, ChatWriteForbidden):
            return

    status = await m.reply_text(m.lang["vcinfo_fetching"])

    # ── Fetch participants via PyTgCalls ────────────────────────────────────
    try:
        # get_assistant returns the PyTgCalls client assigned to this chat
        pytgcalls_client = await db.get_assistant(chat_id)
        participants = await pytgcalls_client.get_participants(chat_id)
    except Exception as exc:
        try:
            return await status.edit_text(
                m.lang["vcinfo_fetch_error"].format(str(exc)[:200])
            )
        except (ChatSendPlainForbidden, ChatWriteForbidden):
            return

    # ── Guard: empty VC ─────────────────────────────────────────────────────
    if not participants:
        try:
            return await status.edit_text(m.lang["vcinfo_empty"])
        except (ChatSendPlainForbidden, ChatWriteForbidden):
            return

    # ── Build message lines ─────────────────────────────────────────────────
    lines: list[str] = [m.lang["vcinfo_header"].format(m.chat.title)]

    for idx, p in enumerate(participants, start=1):
        # Mute icon
        mute_icon = "🔇" if getattr(p, "muted", False) else "🎙️"

        # Volume (pytgcalls stores 0-200, default 100)
        volume = getattr(p, "volume", 100) or 100

        # Screen-share: pytgcalls uses video_stopped=False when sharing
        is_sharing = (getattr(p, "video_stopped", True) is False)
        screen_str = m.lang["vcinfo_screen"] if is_sharing else ""

        # Resolve name
        name = await _resolve_name(p.user_id)

        lines.append(
            m.lang["vcinfo_row"].format(idx, mute_icon, name, volume, screen_str)
        )

    lines.append(m.lang["vcinfo_footer"].format(len(participants)))

    full_text = "".join(lines)

    # ── Send (with fallback to file for huge VCs) ───────────────────────────
    try:
        if len(full_text) <= 4096:
            await status.edit_text(full_text, disable_web_page_preview=True)
        else:
            # Too long → send as plain-text document
            filename = f"vcinfo_{chat_id}.txt"
            with open(filename, "w", encoding="utf-8") as fh:
                # Strip HTML tags for the .txt fallback
                import re
                clean = re.sub(r"<[^>]+>", "", full_text)
                fh.write(clean)

            await status.delete()
            await m.reply_document(
                document=filename,
                caption=m.lang["vcinfo_file_caption"].format(len(participants)),
            )

            try:
                os.remove(filename)
            except OSError:
                pass

    except (ChatSendPlainForbidden, ChatWriteForbidden):
        pass
