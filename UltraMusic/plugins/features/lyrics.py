# ==============================================================================
# lyrics.py - Song Lyrics Command (/lyrics)
# ==============================================================================
# This plugin fetches song lyrics from the free, keyless lyrics.ovh API.
#
# Usage:
#   /lyrics <artist> - <title>     → e.g. /lyrics Coldplay - Yellow
#   /lyrics <free text>            → tried as-is, then split on "-" as a
#                                     fallback to guess artist/title
#   /lyrics (no text)              → falls back to the title of the track
#                                     currently playing in this chat's queue
#
# Notes:
# - Uses aiohttp (already a project dependency) with a short-lived
#   ClientSession per call, same pattern as helpers/_thumbnails.py.
# - No API key required. On any failure (not found, network error, bad
#   response) the user gets a clear "lyrics not found" message - it never
#   raises/crashes the handler.
# - Telegram messages are capped at 4096 characters. Long lyrics are split
#   across multiple messages instead of being truncated or rejected.
# ==============================================================================

import logging

import aiohttp
from pyrogram import filters
from pyrogram.types import Message

from UltraMusic import app, queue

logger = logging.getLogger(__name__)

LYRICS_API = "https://api.lyrics.ovh/v1/{artist}/{title}"

# Telegram hard limit is 4096 chars; stay a bit under it to leave room for
# the <blockquote> wrapper tags added around each chunk.
MAX_CHUNK = 4000


async def _fetch_lyrics(artist: str, title: str) -> str | None:
    """Query lyrics.ovh for a given artist/title pair.

    Returns the lyrics text on success, or None if not found / on error.
    Never raises - all failures are swallowed and logged.
    """
    url = LYRICS_API.format(artist=artist.strip(), title=title.strip())
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
    except Exception as e:
        logger.warning(f"⚠️ lyrics.ovh request failed for '{artist} - {title}': {e}")
        return None

    lyrics = data.get("lyrics")
    if not lyrics or not lyrics.strip():
        return None

    return lyrics.strip()


def _split_query(query: str) -> tuple[str, str] | None:
    """Split a free-text query like 'Artist - Title' into (artist, title)."""
    if "-" not in query:
        return None

    artist, _, title = query.partition("-")
    artist, title = artist.strip(), title.strip()
    if not artist or not title:
        return None

    return artist, title


async def _resolve_lyrics(query: str) -> str | None:
    """Try a few strategies to resolve lyrics from a raw query string.

    1. If the query contains "artist - title", try that split directly.
    2. Otherwise (or if step 1 fails), try the whole query as both the
       "artist" and the "title" slot - lyrics.ovh is lenient enough that
       this still resolves many well-known single-string queries.
    """
    split = _split_query(query)
    if split:
        artist, title = split
        lyrics = await _fetch_lyrics(artist, title)
        if lyrics:
            return lyrics

    # Fallback: treat the full query as the title, with no specific artist
    # guess - some providers/aliases on lyrics.ovh still resolve this.
    lyrics = await _fetch_lyrics(query, query)
    if lyrics:
        return lyrics

    return None


def _split_into_chunks(text: str, limit: int = MAX_CHUNK) -> list[str]:
    """Split long text into chunks <= limit chars, breaking on line boundaries
    where possible so words/lines are never cut mid-way.
    """
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        chunks.append(remaining)

    return chunks


@app.on_message(
    filters.command(["lyrics"])
    & filters.group
    & ~app.bl_users
)
async def lyrics_command(_, m: Message) -> None:
    """Handle /lyrics <query> - fetch and send song lyrics."""

    query = m.text.split(None, 1)[1].strip() if len(m.command) > 1 else ""

    # No text given - fall back to the currently playing track's title.
    if not query:
        current = queue.get_current(m.chat.id)
        if not current or not getattr(current, "title", None):
            return await m.reply_text(
                "<blockquote>❌ ɴᴏ ꜱᴏɴɢ ɴᴀᴍᴇ ᴘʀᴏᴠɪᴅᴇᴅ ᴀɴᴅ ɴᴏᴛʜɪɴɢ ɪꜱ ᴄᴜʀʀᴇɴᴛʟʏ ᴘʟᴀʏɪɴɢ.</blockquote>\n\n"
                "<blockquote><b>ᴜꜱᴀɢᴇ:</b>\n"
                "• `/lyrics Coldplay - Yellow`\n"
                "• `/lyrics` (while a song is playing)</blockquote>"
            )
        channel_name = getattr(current, "channel_name", None)
        query = f"{channel_name} - {current.title}" if channel_name else current.title

    status = await m.reply_text("🔎 <blockquote>ꜱᴇᴀʀᴄʜɪɴɢ ꜰᴏʀ ʟʏʀɪᴄꜱ...</blockquote>")

    try:
        lyrics = await _resolve_lyrics(query)
    except Exception as e:
        logger.error(f"❌ Unexpected error resolving lyrics for '{query}': {e}", exc_info=True)
        lyrics = None

    if not lyrics:
        return await status.edit_text(
            "<blockquote>❌ ʟʏʀɪᴄꜱ ɴᴏᴛ ꜰᴏᴜɴᴅ.</blockquote>\n\n"
            "<blockquote><i>ᴛʀʏ ᴛʜᴇ ꜰᴏʀᴍᴀᴛ:</i> `/lyrics Artist - Title`</blockquote>"
        )

    chunks = _split_into_chunks(lyrics)

    try:
        await status.edit_text(
            f"🎤 <blockquote><b>ʟʏʀɪᴄꜱ:</b> {query}</blockquote>\n\n"
            f"<blockquote>{chunks[0]}</blockquote>"
        )
        for chunk in chunks[1:]:
            await m.reply_text(f"<blockquote>{chunk}</blockquote>")
    except Exception as e:
        logger.error(f"❌ Failed to send lyrics for '{query}': {e}", exc_info=True)
        await status.edit_text("<blockquote>❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ꜱᴇɴᴅ ʟʏʀɪᴄꜱ.</blockquote>")
