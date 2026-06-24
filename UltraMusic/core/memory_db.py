# ==============================================================================
# memory_db.py - In-Memory Database Manager (DATABASE_MODE=memory)
# ==============================================================================
# ⚠️  WARNING — READ BEFORE USING IN PRODUCTION  ⚠️
# MemoryDB stores EVERYTHING (sudoers, chats, language settings, blacklists,
# auth users, loop/autoleave/autoend toggles, top tracks, etc.) in plain
# Python dicts/lists/sets that live ONLY in this process's RAM.
#
#   • ALL data is permanently lost on every restart, crash, or redeploy.
#   • There is no persistence, no backup, no replication.
#   • This mode is intended ONLY for quick local testing / development where
#     you don't want to stand up a real MongoDB instance.
#   • Do NOT use DATABASE_MODE=memory for a production bot serving real
#     users/groups — they will lose their settings (sudo list, language,
#     auth users, blacklist, etc.) every time the bot restarts.
#
# This class is a drop-in replacement for core/mongo.py's MongoDB class:
# same public method names, same parameters, same async-ness, same return
# *shapes* (a method that returns a list in MongoDB returns a list here too,
# etc.). It is built by mirroring core/mongo.py method-by-method — see that
# file's section comments (CACHE, AUTH METHODS, ASSISTANT METHODS, ...) which
# are intentionally kept in the same order/names here for easy side-by-side
# comparison.
#
# Two design notes worth knowing if you touch this file:
# 1. migrate_coll() and load_cache() are no-ops here. In MongoDB they exist to
#    migrate/preload data FROM a real database — there is nothing to migrate
#    or preload from when everything already starts empty in RAM.
# 2. connect()/close() are no-ops (just log a line) since there is no real
#    connection to open or close in memory mode.
# ==============================================================================

from random import randint
from time import time

from UltraMusic import config, logger, userbot


class MemoryDB:
    def __init__(self):
        """Initialize all in-memory storage. Everything starts empty."""
        # CACHE (mirrors MongoDB's in-memory runtime state exactly)
        self.admin_list = {}
        self.admin_cache_time = {}
        self.active_calls = {}          # <-- accessed directly by several plugins, not just via get/add/remove_call
        self.muted_calls = {}
        self.volume_calls: dict[int, int] = {}
        self.blacklisted = []           # <-- accessed directly (chat blacklist) by several plugins
        self.notified = []              # <-- accessed directly by plugins/information/start.py
        self.logger = False
        self.maintenance = False
        self.gbanned_users = []
        self.vplay_enabled = config.VIDEO_PLAY

        self.assistant = {}
        self.last_played: dict[int, dict] = {}

        self.auth: dict[int, set[int]] = {}

        self.chats: list[int] = []
        self.lang: dict[int, str] = {}
        self.play_mode: list[int] = []
        self.users: list[int] = []

        # Generic key->doc store, mirrors MongoDB's self.cache (the "cache"
        # collection) for every method that does cache.find_one/update_one/
        # delete_one keyed by a string _id (autoleave_*, autoend_*, loop_*,
        # cplay_*, audio_bitrate_*, video_quality_*, cleanmode_*, sudoers,
        # bl_users, gbanned_users, logger, maintenance, vplay_toggle, ...).
        self._cache: dict[str, dict] = {}

        # Top-tracks counters
        self._top_global: dict[str, int] = {}
        self._top_chats: dict[int, dict[str, int]] = {}
        self._top_users: dict[int, dict[str, int]] = {}

    # ==========================================================================
    # CONNECTION (no-ops — nothing to connect to in memory mode)
    # ==========================================================================
    async def connect(self) -> None:
        logger.info(
            "🧠 DATABASE_MODE=memory — skipping MongoDB connection, using in-process storage. "
            "ALL DATA WILL BE LOST ON RESTART."
        )

    async def close(self) -> None:
        logger.info("🧠 In-memory database mode: nothing to close.")

    # CACHE
    async def get_call(self, chat_id: int) -> bool:
        return chat_id in self.active_calls

    async def add_call(self, chat_id: int) -> None:
        self.active_calls[chat_id] = 1

    async def remove_call(self, chat_id: int) -> None:
        self.active_calls.pop(chat_id, None)
        self.muted_calls.pop(chat_id, None)
        self.volume_calls.pop(chat_id, None)

    async def get_volume(self, chat_id: int) -> int:
        return self.volume_calls.get(chat_id, 100)

    async def set_volume(self, chat_id: int, vol: int) -> None:
        self.volume_calls[chat_id] = max(0, min(200, vol))

    async def save_last_played(self, chat_id: int, media_data: dict) -> None:
        self.last_played[chat_id] = dict(media_data)

    async def get_last_played(self, chat_id: int) -> dict | None:
        return self.last_played.get(chat_id)

    async def playing(self, chat_id: int, paused: bool = None) -> bool | None:
        if paused is not None:
            self.active_calls[chat_id] = int(not paused)
        return bool(self.active_calls.get(chat_id, 0))

    async def muted(self, chat_id: int, muted: bool = None) -> bool:
        """Get or set the mute state of the voice chat for a given chat_id."""
        if muted is not None:
            self.muted_calls[chat_id] = bool(muted)
        return self.muted_calls.get(chat_id, False)

    async def get_admins(self, chat_id: int, reload: bool = False) -> list[int]:
        from UltraMusic.helpers._admins import reload_admins

        current_time = time()
        cache_age = current_time - self.admin_cache_time.get(chat_id, 0)

        if chat_id not in self.admin_list or reload or cache_age > 900:  # 15 minutes
            self.admin_list[chat_id] = await reload_admins(chat_id)
            self.admin_cache_time[chat_id] = current_time
        return self.admin_list[chat_id]

    # AUTH METHODS
    async def is_auth(self, chat_id: int, user_id: int) -> bool:
        return user_id in self.auth.get(chat_id, set())

    async def add_auth(self, chat_id: int, user_id: int) -> None:
        self.auth.setdefault(chat_id, set()).add(user_id)

    async def rm_auth(self, chat_id: int, user_id: int) -> None:
        self.auth.setdefault(chat_id, set()).discard(user_id)

    # ASSISTANT METHODS
    async def set_assistant(self, chat_id: int) -> int:
        num = randint(1, len(userbot.clients))
        self.assistant[chat_id] = num
        return num

    async def get_assistant(self, chat_id: int):
        from UltraMusic import tune

        if chat_id not in self.assistant:
            await self.set_assistant(chat_id)

        # Check if assigned assistant is out of range (e.g., assistant was removed)
        if self.assistant[chat_id] > len(userbot.clients):
            await self.set_assistant(chat_id)

        return tune.clients[self.assistant[chat_id] - 1]

    async def get_client(self, chat_id: int):
        if chat_id not in self.assistant:
            await self.get_assistant(chat_id)

        if self.assistant[chat_id] > len(userbot.clients):
            await self.set_assistant(chat_id)

        idx = self.assistant[chat_id] - 1
        if 0 <= idx < len(userbot.clients):
            return userbot.clients[idx]
        return None

    # BLACKLIST METHODS
    # NOTE: deliberately mirrors MongoDB's exact (slightly asymmetric)
    # behavior: add_blacklist always appends to self.blacklisted for chats
    # (no dedup, matching the original's unconditional .append before the
    # Mongo $addToSet dedup), while del_blacklist calls .remove() unguarded
    # for chats (will raise ValueError if the id isn't present) — same as
    # core/mongo.py's del_blacklist. This was a deliberate parity choice, not
    # an oversight: see step-1 review notes.
    async def add_blacklist(self, chat_id: int) -> None:
        if str(chat_id).startswith("-"):
            self.blacklisted.append(chat_id)
            doc = self._cache.setdefault(
                "bl_chats", {"_id": "bl_chats", "chat_ids": []})
            if chat_id not in doc["chat_ids"]:
                doc["chat_ids"].append(chat_id)
            return
        doc = self._cache.setdefault(
            "bl_users", {"_id": "bl_users", "user_ids": []})
        if chat_id not in doc["user_ids"]:
            doc["user_ids"].append(chat_id)

    async def del_blacklist(self, chat_id: int) -> None:
        if str(chat_id).startswith("-"):
            self.blacklisted.remove(chat_id)
            doc = self._cache.setdefault(
                "bl_chats", {"_id": "bl_chats", "chat_ids": []})
            if chat_id in doc["chat_ids"]:
                doc["chat_ids"].remove(chat_id)
            return
        doc = self._cache.setdefault(
            "bl_users", {"_id": "bl_users", "user_ids": []})
        if chat_id in doc["user_ids"]:
            doc["user_ids"].remove(chat_id)

    async def get_blacklisted(self, chat: bool = False) -> list[int]:
        if chat:
            if not self.blacklisted:
                doc = self._cache.get("bl_chats")
                self.blacklisted.extend(doc.get("chat_ids", []) if doc else [])
            return self.blacklisted
        doc = self._cache.get("bl_users")
        return doc.get("user_ids", []) if doc else []

    # CHAT METHODS
    async def is_chat(self, chat_id: int) -> bool:
        return chat_id in self.chats

    async def add_chat(self, chat_id: int) -> None:
        if not await self.is_chat(chat_id):
            self.chats.append(chat_id)

    async def rm_chat(self, chat_id: int) -> None:
        if await self.is_chat(chat_id):
            self.chats.remove(chat_id)

    async def get_chats(self) -> list:
        return self.chats

    # LANGUAGE METHODS
    async def set_lang(self, chat_id: int, lang_code: str):
        self.lang[chat_id] = lang_code

    async def get_lang(self, chat_id: int) -> str:
        if chat_id not in self.lang:
            self.lang[chat_id] = "ar"
        return self.lang[chat_id]

    # MAINTENANCE MODE METHODS
    async def set_maintenance(self, status: bool) -> None:
        self.maintenance = status

    async def get_maintenance(self) -> bool:
        return self.maintenance

    # VPLAY TOGGLE METHODS
    async def get_vplay_enabled(self) -> bool:
        return self.vplay_enabled

    async def set_vplay_enabled(self, enabled: bool) -> None:
        self.vplay_enabled = enabled

    # GLOBAL BAN METHODS
    async def add_gban(self, user_id: int) -> None:
        if user_id not in self.gbanned_users:
            self.gbanned_users.append(user_id)

    async def del_gban(self, user_id: int) -> None:
        if user_id in self.gbanned_users:
            self.gbanned_users.remove(user_id)

    async def get_gbanned(self) -> list[int]:
        return self.gbanned_users

    async def is_gbanned(self, user_id: int) -> bool:
        return user_id in self.gbanned_users

    # LOGGER METHODS
    async def is_logger(self) -> bool:
        return self.logger

    async def get_logger(self) -> bool:
        return self.logger

    async def set_logger(self, status: bool) -> None:
        self.logger = status

    # CHANNEL PLAY METHODS
    async def get_cmode(self, chat_id: int) -> int | None:
        doc = self._cache.get(f"cplay_{chat_id}")
        return doc.get("channel_id") if doc else None

    async def set_cmode(self, chat_id: int, channel_id: int | None) -> None:
        key = f"cplay_{chat_id}"
        if channel_id is None:
            self._cache.pop(key, None)
        else:
            self._cache[key] = {"_id": key, "channel_id": channel_id}

    async def get_group_for_channel(self, channel_id: int) -> int | None:
        for key, doc in self._cache.items():
            if key.startswith("cplay_") and doc.get("channel_id") == channel_id:
                group_id_str = key.replace("cplay_", "")
                try:
                    return int(group_id_str)
                except ValueError:
                    return None
        return None

    # AUTO LEAVE METHODS
    async def get_autoleave(self, chat_id: int) -> bool:
        doc = self._cache.get(f"autoleave_{chat_id}")
        return doc.get("enabled", False) if doc else False

    async def set_autoleave(self, chat_id: int, enabled: bool) -> None:
        key = f"autoleave_{chat_id}"
        self._cache[key] = {"_id": key, "enabled": enabled}

    # AUTO END METHODS
    async def get_autoend(self, chat_id: int) -> bool:
        doc = self._cache.get(f"autoend_{chat_id}")
        return doc.get("enabled", False) if doc else False

    async def set_autoend(self, chat_id: int, enabled: bool) -> None:
        key = f"autoend_{chat_id}"
        self._cache[key] = {"_id": key, "enabled": enabled}

    # LOOP MODE METHODS
    async def get_loop(self, chat_id: int) -> int:
        doc = self._cache.get(f"loop_{chat_id}")
        return doc.get("mode", 0) if doc else 0

    async def set_loop(self, chat_id: int, mode: int) -> None:
        key = f"loop_{chat_id}"
        if mode == 0:
            self._cache.pop(key, None)
        else:
            self._cache[key] = {"_id": key, "mode": mode}

    # PLAY MODE METHODS
    async def get_play_mode(self, chat_id: int) -> bool:
        return chat_id in self.play_mode

    async def set_play_mode(self, chat_id: int, remove: bool = False) -> None:
        if remove:
            if chat_id in self.play_mode:
                self.play_mode.remove(chat_id)
        else:
            if chat_id not in self.play_mode:
                self.play_mode.append(chat_id)

    # SUDO METHODS
    async def add_sudo(self, user_id: int) -> None:
        doc = self._cache.setdefault("sudoers", {"_id": "sudoers", "user_ids": []})
        if user_id not in doc["user_ids"]:
            doc["user_ids"].append(user_id)

    async def del_sudo(self, user_id: int) -> None:
        doc = self._cache.get("sudoers")
        if doc and user_id in doc.get("user_ids", []):
            doc["user_ids"].remove(user_id)

    async def get_sudoers(self) -> list[int]:
        doc = self._cache.get("sudoers")
        return doc.get("user_ids", []) if doc else []

    # USER METHODS
    async def is_user(self, user_id: int) -> bool:
        return user_id in self.users

    async def add_user(self, user_id: int) -> None:
        if not await self.is_user(user_id):
            self.users.append(user_id)

    async def rm_user(self, user_id: int) -> None:
        if await self.is_user(user_id):
            self.users.remove(user_id)

    async def get_users(self) -> list:
        return self.users

    async def migrate_coll(self) -> None:
        """No-op: nothing to migrate from in memory mode (see module docstring)."""
        return

    async def load_cache(self) -> None:
        """No-op: nothing to preload from in memory mode (see module docstring)."""
        return

    # ============================================================
    # AUDIO BITRATE METHODS
    # ============================================================
    async def get_audio_bitrate(self, chat_id: int) -> str:
        doc = self._cache.get(f"audio_bitrate_{chat_id}")
        return doc.get("bitrate", "128k") if doc else "128k"

    async def set_audio_bitrate(self, chat_id: int, bitrate: str) -> None:
        key = f"audio_bitrate_{chat_id}"
        self._cache[key] = {"_id": key, "bitrate": bitrate}

    # ============================================================
    # VIDEO QUALITY METHODS
    # ============================================================
    async def get_video_quality(self, chat_id: int) -> str:
        doc = self._cache.get(f"video_quality_{chat_id}")
        return doc.get("quality", "720") if doc else "720"

    async def set_video_quality(self, chat_id: int, quality: str) -> None:
        key = f"video_quality_{chat_id}"
        self._cache[key] = {"_id": key, "quality": quality}

    # ============================================================
    # TOP TRACKS METHODS
    # ============================================================
    async def increment_track(self, vidid: str, chat_id: int, user_id: int) -> None:
        """Increment play count for a track globally, per chat, and per user."""
        self._top_global[vidid] = self._top_global.get(vidid, 0) + 1

        chat_counts = self._top_chats.setdefault(chat_id, {})
        chat_counts[vidid] = chat_counts.get(vidid, 0) + 1

        user_counts = self._top_users.setdefault(user_id, {})
        user_counts[vidid] = user_counts.get(vidid, 0) + 1

    async def get_global_tops(self) -> dict:
        """Get top 10 tracks globally by play count."""
        items = sorted(self._top_global.items(),
                        key=lambda kv: kv[1], reverse=True)[:10]
        return dict(items)

    async def get_chat_tops(self, chat_id: int) -> dict:
        """Get top 10 tracks in a specific chat."""
        counts = self._top_chats.get(chat_id, {})
        items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
        return dict(items)

    async def get_user_tops(self, user_id: int) -> dict:
        """Get top 10 tracks for a specific user."""
        counts = self._top_users.get(user_id, {})
        items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
        return dict(items)

    # ============================================================
    # CLEAN MODE METHODS
    # ============================================================
    async def is_cleanmode_on(self, chat_id: int) -> bool:
        doc = self._cache.get(f"cleanmode_{chat_id}")
        return doc.get("enabled", False) if doc else False

    async def cleanmode_on(self, chat_id: int) -> None:
        key = f"cleanmode_{chat_id}"
        self._cache[key] = {"_id": key, "enabled": True}

    async def cleanmode_off(self, chat_id: int) -> None:
        key = f"cleanmode_{chat_id}"
        self._cache[key] = {"_id": key, "enabled": False}
