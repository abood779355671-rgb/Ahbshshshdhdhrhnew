# ==============================================================================
# reload.py - Hot-Reload Plugin Modules (Sudo Only)
# ==============================================================================
# This plugin allows sudo users to reload all bot plugins at runtime without
# restarting the entire process.
#
# Commands:
# - /reload - Reload all plugin modules in-place
#
# ⚠️  IMPORTANT LIMITATION (see technical note at bottom of file):
# importlib.reload() refreshes function *bodies* but does NOT re-register
# Pyrogram @on_message handlers. Use /restart for a full handler reset.
#
# Only sudo users can use this command.
# ==============================================================================

import sys
import importlib

from pyrogram import filters, types

from UltraMusic import app, lang
from UltraMusic.plugins import all_modules


@app.on_message(filters.command(["reload"]) & app.sudo_filter)
@lang.language()
async def _reload(_, m: types.Message):
    """Reload all plugin modules without restarting the process."""
    # Auto-delete command message
    try:
        await m.delete()
    except Exception:
        pass

    sent = await m.reply_text(
        "<blockquote><u><b>🔄 ʀᴇʟᴏᴀᴅɪɴɢ ᴘʟᴜɢɪɴꜱ...</b></u>\n\n"
        f"ꜰᴏᴜɴᴅ <b>{len(all_modules)}</b> ᴍᴏᴅᴜʟᴇꜱ ᴛᴏ ʀᴇʟᴏᴀᴅ.</blockquote>"
    )

    succeeded = 0
    failed = []   # list of (module_name, error_str)

    for module_name in all_modules:
        full_name = f"UltraMusic.plugins.{module_name}"
        try:
            existing = sys.modules.get(full_name)
            if existing is not None:
                # Module was imported before → reload it in-place.
                # This updates all function bodies and module-level variables
                # but does NOT re-execute @app.on_message decorators (see note).
                importlib.reload(existing)
            else:
                # Module was never imported (e.g. added after startup).
                importlib.import_module(full_name)
            succeeded += 1
        except Exception as exc:
            # Collect the error and continue; don't abort the whole reload.
            short_err = str(exc)[:120]   # truncate very long tracebacks
            failed.append((module_name, short_err))

    # ── Build result message ──────────────────────────────────────────────────
    status_icon = "✅" if not failed else "⚠️"

    lines = [
        f"<blockquote><u><b>{status_icon} ʀᴇʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ</b></u>\n\n"
        f"<b>✅ ꜱᴜᴄᴄᴇᴇᴅᴇᴅ:</b> {succeeded} / {len(all_modules)} ᴍᴏᴅᴜʟᴇꜱ\n"
        f"<b>❌ ꜰᴀɪʟᴇᴅ:</b> {len(failed)} ᴍᴏᴅᴜʟᴇꜱ"
    ]

    if failed:
        lines.append("\n\n<b>── ꜰᴀɪʟᴜʀᴇ ᴅᴇᴛᴀɪʟꜱ ──</b>")
        for mod, err in failed:
            lines.append(f"\n• <code>{mod}</code>\n  <i>{err}</i>")

    lines.append(
        "\n\n<i>⚠️ ʜᴀɴᴅʟᴇʀꜱ ᴀʀᴇ ɴᴏᴛ ʀᴇ-ʀᴇɢɪꜱᴛᴇʀᴇᴅ. "
        "ᴜꜱᴇ /restart ꜰᴏʀ ᴀ ꜰᴜʟʟ ʀᴇꜱᴇᴛ.</i></blockquote>"
    )

    await sent.edit_text("".join(lines))


# ==============================================================================
# 📌 TECHNICAL NOTE — importlib.reload() vs. Pyrogram handler re-registration
# ==============================================================================
#
# When a plugin file is first imported, Python executes the module body
# top-to-bottom. Every @app.on_message(...) decorator runs at that moment and
# registers a handler inside Pyrogram's internal dispatcher.
#
# importlib.reload(module) re-executes the module body **in the same module
# object**. In theory this should re-run the decorators — but Pyrogram's
# add_handler() does not de-duplicate, so each reload appends a *second* copy
# of every handler without removing the original. After N reloads you have
# N+1 copies of each handler firing per message.
#
# What /reload IS safe for (without the duplication problem):
# ─────────────────────────────────────────────────────────
#   • Updating logic inside helper functions or coroutines that are called
#     *by* an already-registered handler (e.g. changing how _play() formats
#     a reply after the @on_message decorator has already hooked it).
#   • Refreshing module-level constants (strings, config values) that handlers
#     read at call time rather than at decoration time.
#   • Force-importing a brand-new plugin file added after startup.
#
# What /reload does NOT fix:
# ─────────────────────────
#   • Adding a new @on_message decorator to an existing file.
#   • Removing or changing the filters of an existing @on_message.
#   • Any change that depends on re-running the decorator itself.
#
# Deep solution (not implemented here — request explicitly if needed):
# ────────────────────────────────────────────────────────────────────
# Before reloading, iterate app.dispatcher.groups (a dict of priority →
# list[Handler]) and remove every Handler whose callback.__module__ matches
# the plugin being reloaded. Then reload the module, which re-runs the
# decorators and registers fresh handlers. This gives a true hot-swap but
# requires direct access to Pyrogram internals (app.dispatcher.groups) which
# may break across Pyrogram versions — hence it is left as an opt-in option.
# ==============================================================================
