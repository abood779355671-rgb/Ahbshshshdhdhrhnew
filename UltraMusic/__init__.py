"""
˹ᴜʟᴛʀᴀ ᴍᴜꜱɪᴄ˼ - Advanced Telegram Music Bot

This is the main initialization module that sets up logging, configuration,
and all core components required for the bot to function.
"""

import asyncio
import time
import logging
from logging.handlers import RotatingFileHandler
from typing import List

from pyrogram.errors import ChannelInvalid

# Configure logging
logging.basicConfig(
    format="[%(asctime)s - %(levelname)s] - %(name)s: %(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    handlers=[
        RotatingFileHandler("log.txt", maxBytes=10485760, backupCount=5),
        logging.StreamHandler(),
    ],
    level=logging.INFO,
)

# Reduce noise from third-party libraries
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("ntgcalls").setLevel(logging.CRITICAL)
logging.getLogger("pymongo").setLevel(logging.ERROR)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("pytgcalls").setLevel(logging.ERROR)

logger = logging.getLogger("UltraMusic")


# ==============================================================================
# TelegramLogHandler - Forward ERROR+ records to the Telegram logger channel
# ==============================================================================
# This handler sits alongside the existing RotatingFileHandler + StreamHandler.
# It does NOT replace them; logging.basicConfig above remains unchanged.
#
# ── Why the import of send_log lives inside emit() ───────────────────────────
# UltraMusic.helpers._logger_channel.send_log() performs a *late* local import
# of `app` and `config` from UltraMusic (see _logger_channel.py header).
# If we imported send_log here at module level it would work — _logger_channel
# itself is safe to import early because it has no top-level UltraMusic imports.
# However placing the import inside emit() gives an extra safety layer: if for
# any reason emit() fires before helpers are on sys.modules, the bare
# ImportError is caught by the outer try/except and the handler silently skips.
#
# ── Why asyncio.get_running_loop() guards the task creation ──────────────────
# emit() may be called at import time (before the asyncio event loop starts).
# asyncio.get_running_loop() raises RuntimeError when there is no running loop,
# so we catch it and return early — no log is lost (it's still in the file/
# console handlers), we just skip the Telegram delivery for those early records.
# ==============================================================================
class TelegramLogHandler(logging.Handler):
    """Async Telegram forwarding handler — ERROR level and above only."""

    def emit(self, record: logging.LogRecord) -> None:
        # Gate 1: only forward errors and criticals to avoid channel flooding.
        if record.levelno < logging.ERROR:
            return

        # Gate 2: skip if no event loop is running (import / pre-boot phase).
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        # Gate 3: import send_log locally — avoids circular-import at module
        # load time and is safe because by the time an ERROR fires at runtime,
        # all helpers are fully initialized.
        try:
            from UltraMusic.helpers._logger_channel import send_log  # noqa: PLC0415
        except ImportError:
            return

        try:
            # Format the record exactly as the other handlers do.
            text = self.format(record)
            # fire-and-forget: we must not await inside a sync method.
            loop.create_task(send_log(
                f"⚠️ <b>[{record.levelname}]</b> — <code>{record.name}</code>\n\n"
                f"<pre>{text[:3500]}</pre>"  # Telegram message cap: 4096 chars
            ))
        except Exception:
            # Never let the logging system crash the bot.
            pass


# Attach the Telegram handler to our named logger.
# setLevel on the handler itself is redundant (emit() gates on ERROR already)
# but makes the intent explicit when inspecting logger.handlers at runtime.
_tg_handler = TelegramLogHandler()
_tg_handler.setFormatter(logging.Formatter(
    "[%(asctime)s - %(levelname)s] - %(name)s: %(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
))
_tg_handler.setLevel(logging.ERROR)
logger.addHandler(_tg_handler)


def _asyncio_exception_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    exc = context.get("exception")
    if isinstance(exc, ChannelInvalid):
        logger.warning("Ignoring CHANNEL_INVALID update (channel probably removed).")
        return
    loop.default_exception_handler(context)


def set_exception_handler() -> None:
    """Call this inside an async context (after event loop is running)."""
    try:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(_asyncio_exception_handler)
    except RuntimeError:
        pass  # No running loop at import time — will be set in main()
# Version
__version__ = "3.0.1"

# Load configuration
from config import Config

config = Config()
config.check()

# Global task list for background tasks
tasks: List = []
boot: float = time.time()

# Initialize bot client
from UltraMusic.core.bot import Bot
app = Bot()

# Ensure required directories exist
from UltraMusic.core.dir import ensure_dirs
ensure_dirs()

# Initialize userbot/assistant clients
from UltraMusic.core.userbot import Userbot
userbot = Userbot()

# Initialize database connection
# DATABASE_MODE=memory uses an in-memory drop-in replacement (core/memory_db.py)
# instead of a real MongoDB connection. Default is "mongo" so any existing
# deployment keeps its current behavior unless DATABASE_MODE is set explicitly.
# getattr(..., "mongo") is used defensively in case config.py hasn't been
# updated yet with the DATABASE_MODE variable.
if getattr(config, "DATABASE_MODE", "mongo") == "memory":
    from UltraMusic.core.memory_db import MemoryDB
    db = MemoryDB()
    logger.warning(
        "🧠 DATABASE_MODE=memory is active — using in-memory storage. "
        "ALL bot data (sudoers, settings, blacklist, etc.) will be LOST on restart. "
        "Do not use this mode for a real production bot."
    )
else:
    from UltraMusic.core.mongo import MongoDB
    db = MongoDB()

# Initialize language system
from UltraMusic.core.lang import Language
lang = Language()

# Initialize Telegram and YouTube utilities
from UltraMusic.core.telegram import Telegram
from UltraMusic.core.youtube import YouTube
tg = Telegram()
yt = YouTube()

# Initialize preload manager for background track downloading
from UltraMusic.core.preload import PreloadManager
preload = PreloadManager()

# Initialize queue manager
from UltraMusic.helpers import Queue
queue = Queue()

# Initialize call handler
from UltraMusic.core.calls import TgCall
tune = TgCall()


async def stop() -> None:
    """
    Gracefully shutdown the bot and all its components.
    
    This function:
    - Cancels all running background tasks
    - Closes bot and userbot connections
    - Closes database connection
    - Logs shutdown completion
    """
    logger.info("🛑 Stopping bot...")
    
    # Cancel all background tasks
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # Expected when cancelling tasks - suppress the error
            pass
        except Exception:
            pass
    
    # Close all connections
    await app.exit()
    await userbot.exit()
    await db.close()
    
    logger.info("✅ Bot stopped successfully.\n")
