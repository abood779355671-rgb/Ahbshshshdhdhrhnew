from pyrogram import filters

from UltraMusic import tune, app, db, lang, queue
from UltraMusic.helpers import can_manage_vc, command


@app.on_message(command(["استئناف"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _resume_last(_, m):
    chat_id = m.chat.id

    if await db.get_call(chat_id):
        return await m.reply_text(m.lang["resume_last_active"])

    doc = await db.get_last_played(chat_id)
    if not doc:
        return await m.reply_text(m.lang["resume_last_empty"])

    sent = await m.reply_text(m.lang["resume_last_resuming"].format(doc.get("title", "?")))

    try:
        from UltraMusic.helpers._dataclass import MediaItem
        media = MediaItem(
            id=doc.get("video_id", ""),
            title=doc.get("title", ""),
            url=doc.get("url", ""),
            duration=doc.get("duration", ""),
            duration_sec=doc.get("duration_sec", 0),
            user=doc.get("user", m.from_user.mention),
            video=doc.get("video", False),
            is_live=False,
        )
        media.time = doc.get("last_time", 1)

        queue.put(chat_id, media)
        seek = max(1, doc.get("last_time", 1))
        await tune.play_media(chat_id, sent, media, seek_time=seek)
    except Exception as e:
        await sent.edit_text(m.lang["resume_last_failed"])
