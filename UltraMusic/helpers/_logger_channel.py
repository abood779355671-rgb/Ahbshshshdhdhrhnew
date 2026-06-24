# ==============================================================================
# _logger_channel.py - Telegram Logger Channel Helper
# ==============================================================================
# Provides a single async helper, send_log(), that forwards a text message to
# the configured Telegram logger channel (config.LOGGER_ID).
#
# ── Circular-import note ──────────────────────────────────────────────────────
# This file is imported from UltraMusic/__init__.py (indirectly, via the
# TelegramLogHandler class).  If we wrote:
#
#     from UltraMusic import app, config   ← TOP OF FILE
#
# Python would try to resolve `UltraMusic` while __init__.py is still
# executing, finding a half-built module object where `app` doesn't exist yet
# → AttributeError / ImportError.
#
# The fix: the imports of `app` and `config` are placed INSIDE send_log() so
# they run only when the function is actually called (runtime), by which point
# UltraMusic/__init__.py has long finished and both `app` and `config` are
# fully available in sys.modules['UltraMusic'].
# ==============================================================================


async def send_log(text: str) -> None:
    """
    Send a log message to the configured Telegram logger channel.

    Behaviour on failure:
    - Any exception (network error, bot not in channel, invalid LOGGER_ID …)
      is swallowed silently — logging helpers must never crash the bot.
    - No retries are attempted; log delivery is best-effort.

    Args:
        text: Plain-text or HTML-formatted message to send.
    """
    try:
        # Late / local import — intentionally NOT at module level.
        # See the circular-import note in the header above.
        from UltraMusic import app, config  # noqa: PLC0415

        if not config.LOGGER_ID:
            return

        await app.send_message(config.LOGGER_ID, text)

    except Exception:
        # Swallow every exception: channel missing, bot banned, Flood wait,
        # partial module during early startup — none of these should bubble up.
        pass
