from pyrogram import filters

from UltraMusic import tune, app, db, lang, queue
from UltraMusic.helpers import can_manage_vc, command


@app.on_message(command(["اعادة"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _replay(_, m):
    try:
        await m.delete()
    except Exception:
        pass

    if not await db.get_call(m.chat.id):
        return await m.reply_text(m.lang["not_playing"])

    media = queue.get_current(m.chat.id)

    if not media:
        return await m.reply_text(m.lang["not_playing"])

    await tune.replay(m.chat.id)
