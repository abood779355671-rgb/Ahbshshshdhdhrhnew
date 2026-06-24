from pyrogram import filters

from UltraMusic import tune, app, db, lang
from UltraMusic.helpers import can_manage_vc, command


@app.on_message(command(["صوت"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _volume(_, m):
    if len(m.command) < 2:
        current = await db.get_volume(m.chat.id)
        return await m.reply_text(f"🔊 الصوت الحالي: {current}%\nالاستخدام: صوت <0-200>")
    try:
        vol = int(m.command[1])
    except ValueError:
        return await m.reply_text("❌ قيمة غير صالحة. استخدم رقماً بين 0 و 200")
    if not 0 <= vol <= 200:
        return await m.reply_text("❌ القيمة يجب أن تكون بين 0 و 200")
    if not await db.get_call(m.chat.id):
        return await m.reply_text(m.lang["not_playing"])
    sent = await m.reply_text("⏳ جاري تغيير الصوت...")
    ok = await tune.change_volume(m.chat.id, vol)
    if ok:
        await sent.edit_text(f"🔊 تم ضبط الصوت على {vol}% بواسطة {m.from_user.mention}")
    else:
        await sent.edit_text("❌ فشل تغيير الصوت - تأكد أن المقطع يشتغل")
