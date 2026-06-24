# ==============================================================================
# toptracks.py - Top Tracks Statistics
# ==============================================================================
# Commands:
#   /topchat   → Top 10 most-played tracks in this group
#   /topglobal → Top 10 most-played tracks across all groups
#   /topuser   → Top 10 most-played tracks by the sender
#
# Track data is recorded via db.increment_track() called from the play handler.
# ==============================================================================

from pyrogram import filters
from pyrogram.types import Message

from UltraMusic import app, db


def _format_list(title: str, tracks: dict) -> str:
    """Format a top-tracks dict into a readable message."""
    if not tracks:
        return f"<blockquote><b>{title}</b>\n\nلا توجد بيانات بعد. شغّل بعض الأغاني أولاً! 🎵</blockquote>"

    lines = [f"<blockquote><b>{title}</b>\n"]
    for rank, (vidid, count) in enumerate(tracks.items(), start=1):
        # vidid is a YouTube ID; build a short link
        url = f"https://youtu.be/{vidid}"
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"<b>{rank}.</b>")
        lines.append(f"{medal} <a href='{url}'>{vidid}</a> — <code>{count}</code> مرة")

    lines.append("</blockquote>")
    return "\n".join(lines)


# ── /topglobal ────────────────────────────────────────────────────────────────

@app.on_message(filters.command(["topglobal", "gtop"]) & filters.group)
async def top_global_cmd(_, message: Message):
    """Show top 10 globally played tracks."""
    msg = await message.reply(
        "<blockquote>⏳ جارٍ جلب أكثر الأغاني تشغيلاً عالمياً...</blockquote>",
        parse_mode="html",
    )
    tracks = await db.get_global_tops()
    text = _format_list("🌍 أكثر 10 أغاني تشغيلاً عالمياً", tracks)
    await msg.edit_text(text, parse_mode="html", disable_web_page_preview=True)


# ── /topchat ──────────────────────────────────────────────────────────────────

@app.on_message(filters.command(["topchat", "ctop"]) & filters.group)
async def top_chat_cmd(_, message: Message):
    """Show top 10 tracks in this group."""
    msg = await message.reply(
        "<blockquote>⏳ جارٍ جلب أكثر الأغاني تشغيلاً في هذه المجموعة...</blockquote>",
        parse_mode="html",
    )
    tracks = await db.get_chat_tops(message.chat.id)
    text = _format_list("📊 أكثر 10 أغاني تشغيلاً في هذه المجموعة", tracks)
    await msg.edit_text(text, parse_mode="html", disable_web_page_preview=True)


# ── /topuser ──────────────────────────────────────────────────────────────────

@app.on_message(filters.command(["topuser", "utop"]) & filters.group)
async def top_user_cmd(_, message: Message):
    """Show top 10 tracks for the requesting user."""
    msg = await message.reply(
        "<blockquote>⏳ جارٍ جلب أكثر أغانيك تشغيلاً...</blockquote>",
        parse_mode="html",
    )
    tracks = await db.get_user_tops(message.from_user.id)
    name = message.from_user.first_name or "المستخدم"
    text = _format_list(f"🎧 أكثر 10 أغاني تشغيلاً لـ {name}", tracks)
    await msg.edit_text(text, parse_mode="html", disable_web_page_preview=True)
