# ==============================================================================
# autoend.py - Auto End Command
# ==============================================================================
# This plugin allows sudo users to enable/disable the auto-end feature.
# When enabled, the assistant will stop the current stream and clear the
# queue after 5 minutes if no real users are in the VC (only the assistant
# is present). Unlike /autoleave, the assistant does NOT leave the voice
# chat — it stays connected and silent, ready for a new /play command.
# ==============================================================================

from pyrogram import filters
from pyrogram.types import Message

from UltraMusic import app, db


@app.on_message(
    filters.command(["autoend"])
    & filters.group
    & ~app.bl_users
)
async def autoend_command(_, m: Message) -> None:
    """Handle /autoend enable or /autoend disable command."""

    # Check if user is sudo user
    if m.from_user.id not in app.sudoers:
        return await m.reply_text(
            "❌ ᴏɴʟʏ ꜱᴜᴅᴏ ᴜꜱᴇʀꜱ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ."
        )

    # Check if subcommand is provided
    if len(m.command) < 2:
        current_status = await db.get_autoend(m.chat.id)
        status_text = "ᴇɴᴀʙʟᴇᴅ" if current_status else "ᴅɪꜱᴀʙʟᴇᴅ"
        return await m.reply_text(
            f"<blockquote>🔧 ᴀᴜᴛᴏ ᴇɴᴅ ꜱᴛᴀᴛᴜꜱ: {status_text}</blockquote>\n\n"
            "<blockquote><b>ᴜꜱᴀɢᴇ:</b>\n"
            "• `/autoend enable` - ᴇɴᴀʙʟᴇ ᴀᴜᴛᴏ ᴇɴᴅ\n"
            "• `/autoend disable` - ᴅɪꜱᴀʙʟᴇ ᴀᴜᴛᴏ ᴇɴᴅ</blockquote>\n\n"
            "<blockquote><i>ᴡʜᴇɴ ᴇɴᴀʙʟᴇᴅ, ᴛʜᴇ ꜱᴛʀᴇᴀᴍ ᴡɪʟʟ ꜱᴛᴏᴘ ᴀɴᴅ ᴛʜᴇ ǫᴜᴇᴜᴇ ᴡɪʟʟ ʙᴇ "
            "ᴄʟᴇᴀʀᴇᴅ ᴀꜰᴛᴇʀ 5 ᴍɪɴᴜᴛᴇꜱ ɪꜰ ɴᴏ ᴜꜱᴇʀꜱ ᴀʀᴇ ʟɪꜱᴛᴇɴɪɴɢ. "
            "ᴛʜᴇ ᴀꜱꜱɪꜱᴛᴀɴᴛ ꜱᴛᴀʏꜱ ɪɴ ᴛʜᴇ ᴠᴏɪᴄᴇ ᴄʜᴀᴛ (ᴅᴏᴇꜱ ɴᴏᴛ ʟᴇᴀᴠᴇ).</i></blockquote>"
        )

    subcommand = m.command[1].lower()

    if subcommand == "enable":
        await db.set_autoend(m.chat.id, True)
        await m.reply_text(
            "✅ <blockquote>ᴀᴜᴛᴏ ᴇɴᴅ ᴇɴᴀʙʟᴇᴅ!</blockquote>\n\n"
            "<blockquote>ᴛʜᴇ ꜱᴛʀᴇᴀᴍ ᴡɪʟʟ ꜱᴛᴏᴘ ᴀɴᴅ ᴛʜᴇ ǫᴜᴇᴜᴇ ᴡɪʟʟ ʙᴇ ᴄʟᴇᴀʀᴇᴅ ᴀꜰᴛᴇʀ "
            "<b>5 ᴍɪɴᴜᴛᴇꜱ</b> ɪꜰ ɴᴏ ᴜꜱᴇʀꜱ ᴀʀᴇ ʟɪꜱᴛᴇɴɪɴɢ. ᴛʜᴇ ᴀꜱꜱɪꜱᴛᴀɴᴛ ꜱᴛᴀʏꜱ ɪɴ ᴛʜᴇ "
            "ᴠᴏɪᴄᴇ ᴄʜᴀᴛ, ʀᴇᴀᴅʏ ꜰᴏʀ ᴀ ɴᴇᴡ /play.</blockquote>"
        )
    elif subcommand == "disable":
        await db.set_autoend(m.chat.id, False)
        await m.reply_text(
            "✅ <blockquote>ᴀᴜᴛᴏ ᴇɴᴅ ᴅɪꜱᴀʙʟᴇᴅ!</blockquote>\n\n"
            "<blockquote>ᴛʜᴇ ꜱᴛʀᴇᴀᴍ ᴡɪʟʟ ᴋᴇᴇᴘ ᴘʟᴀʏɪɴɢ ᴇᴠᴇɴ ᴡʜᴇɴ ɴᴏ ᴏɴᴇ ɪꜱ ʟɪꜱᴛᴇɴɪɴɢ.</blockquote>"
        )
    else:
        await m.reply_text(
            "❌ <blockquote>ɪɴᴠᴀʟɪᴅ ꜱᴜʙᴄᴏᴍᴍᴀɴᴅ!</blockquote>\n\n"
            "<blockquote><b>ᴜꜱᴀɢᴇ:</b>\n"
            "• `/autoend enable`\n"
            "• `/autoend disable`</blockquote>"
        )
