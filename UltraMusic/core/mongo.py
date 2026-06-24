# ==============================================================================
# mongo.py - MongoDB Database Manager
# ==============================================================================
# This file handles all database operations using MongoDB.
# Collections:
# - users: User data (sudo users)
# - chats: Group/chat data (language, channel play mode, authorized users)
# - blacklist: Blacklisted users/chats
# - calls: Active voice call sessions
# - cache: Admin list cache
#
# Features:
# - Async MongoDB operations for better performance
# - Connection pooling for efficiency
# - Admin list caching to reduce database queries
# - Random assistant selection for load balancing
# ==============================================================================

from random import randint
from time import time
import asyncio
import logging

from pymongo import AsyncMongoClient

from UltraMusic import config, logger, userbot


# Suppress non-critical MongoDB background task errors
class MongoBackgroundFilter(logging.Filter):
    def filter(self, record):
        # Suppress AutoReconnect and _OperationCancelled background errors (these are handled internally)
        msg = record.getMessage()
        return not (
            'MongoClient background task encountered an error' in msg or
            ('AutoReconnect' in msg and 'background task' in msg) or
            ('_OperationCancelled' in msg and 'background task' in msg)
        )

logging.getLogger('pymongo.client').addFilter(MongoBackgroundFilter())


class MongoDB:
    def __init__(self):
        """
        Initialize the MongoDB connection.
        """
        self.mongo = AsyncMongoClient(
            config.MONGO_URL,
            serverSelectionTimeoutMS=12500,
            connectTimeoutMS=20000,
            socketTimeoutMS=20000,
            maxPoolSize=20,  # Reduced from 50 to prevent too many open connections
            minPoolSize=5,   # Reduced from 10 to prevent too many open connections
            maxIdleTimeMS=30000,  # Reduced from 45000 - close idle connections faster
            waitQueueTimeoutMS=10000,
            retryWrites=True,
            retryReads=True
        )
        self.db = self.mongo.UltraTune

        self.admin_list = {}  # Cache admin lists
        self.admin_cache_time = {}  # Track cache freshness
        self.active_calls = {}
        self.muted_calls = {}  # Track mute state per chat (in-memory, like active_calls)
        self.volume_calls: dict[int, int] = {}  # chat_id -> volume (0-200), default 100
        self.blacklisted = []
        self.notified = []
        self.cache = self.db.cache
        self.logger = False
        self.maintenance = False  # Maintenance mode status
        self.gbanned_users = []  # Globally banned users
        self.vplay_enabled = config.VIDEO_PLAY

        self.assistant = {}
        self.assistantdb = self.db.assistant
        self.last_playeddb = self.db.last_played

        self.auth = {}
        self.authdb = self.db.auth

        self.chats = []
        self.chatsdb = self.db.chats

        self.lang = {}
        self.langdb = self.db.lang

        self.play_mode = []
        self.playmodedb = self.db.play

        self.users = []
        self.usersdb = self.db.users

    async def connect(self) -> None:
        """Check if we can connect to the database with exponential backoff retry logic.

        Raises:
            SystemExit: If the connection to the database fails after retries.
        """
        max_retries = 3
        retry_delay = 5  # Initial delay in seconds
        
        for attempt in range(1, max_retries + 1):
            try:
                start = time()
                await self.mongo.admin.command("ping")
                logger.info(
                    f"✅ Database connection successful. ({time() - start:.2f}s)")

                # Create indexes for faster queries
                await self.authdb.create_index("_id")
                await self.langdb.create_index("_id")
                await self.cache.create_index("_id")
                await self.cache.create_index("channel_id", sparse=True)

                await self.load_cache()
                return  # Success, exit the function
            except Exception as e:
                if attempt < max_retries:
                    # Exponential backoff: 5s, 10s, 20s
                    wait_time = retry_delay * (2 ** (attempt - 1))
                    logger.warning(f"Database connection attempt {attempt}/{max_retries} failed: {type(e).__name__}. Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    raise SystemExit(
                        f"Database connection failed after {max_retries} attempts: {type(e).__name__}") from e

    async def close(self) -> None:
        """Close the connection to the database."""
        await self.mongo.close()
        logger.info("Database connection closed.")

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
        await self.last_playeddb.update_one(
            {"_id": chat_id},
            {"$set": media_data},
            upsert=True
        )

    async def get_last_played(self, chat_id: int) -> dict | None:
        doc = await self.last_playeddb.find_one({"_id": chat_id})
        return doc

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

        # **PERFORMANCE FIX**: Increased cache from 5 to 15 minutes
        # Reduces MongoDB queries during peak load (15-20 concurrent streams)
        current_time = time()
        cache_age = current_time - self.admin_cache_time.get(chat_id, 0)

        if chat_id not in self.admin_list or reload or cache_age > 900:  # 15 minutes
            self.admin_list[chat_id] = await reload_admins(chat_id)
            self.admin_cache_time[chat_id] = current_time
        return self.admin_list[chat_id]

    # AUTH METHODS
    async def _get_auth(self, chat_id: int) -> set[int]:
        if chat_id not in self.auth:
            doc = await self.authdb.find_one({"_id": chat_id}) or {}
            self.auth[chat_id] = set(doc.get("user_ids", []))
        return self.auth[chat_id]

    async def is_auth(self, chat_id: int, user_id: int) -> bool:
        return user_id in await self._get_auth(chat_id)

    async def add_auth(self, chat_id: int, user_id: int) -> None:
        users = await self._get_auth(chat_id)
        if user_id not in users:
            users.add(user_id)
            await self.authdb.update_one(
                {"_id": chat_id}, {"$addToSet": {"user_ids": user_id}}, upsert=True
            )

    async def rm_auth(self, chat_id: int, user_id: int) -> None:
        users = await self._get_auth(chat_id)
        if user_id in users:
            users.discard(user_id)
            await self.authdb.update_one(
                {"_id": chat_id}, {"$pull": {"user_ids": user_id}}
            )

    # ASSISTANT METHODS
    async def set_assistant(self, chat_id: int) -> int:
        num = randint(1, len(userbot.clients))
        await self.assistantdb.update_one(
            {"_id": chat_id},
            {"$set": {"num": num}},
            upsert=True,
        )
        self.assistant[chat_id] = num
        return num

    async def get_assistant(self, chat_id: int):
        from UltraMusic import tune

        if chat_id not in self.assistant:
            doc = await self.assistantdb.find_one({"_id": chat_id})
            num = doc["num"] if doc else await self.set_assistant(chat_id)
            self.assistant[chat_id] = num

        # Check if assigned assistant is out of range (e.g., assistant was removed)
        if self.assistant[chat_id] > len(userbot.clients):
            # Reassign to a valid assistant
            num = await self.set_assistant(chat_id)
            self.assistant[chat_id] = num

        return tune.clients[self.assistant[chat_id] - 1]

    async def get_client(self, chat_id: int):
        if chat_id not in self.assistant:
            await self.get_assistant(chat_id)
        
        # Check if assigned assistant is out of range
        if self.assistant[chat_id] > len(userbot.clients):
            # Reassign to a valid assistant
            await self.set_assistant(chat_id)
        
        # Dynamically resolve client from ordered clients list (index = num - 1)
        idx = self.assistant[chat_id] - 1
        if 0 <= idx < len(userbot.clients):
            return userbot.clients[idx]
        return None

    # BLACKLIST METHODS
    async def add_blacklist(self, chat_id: int) -> None:
        if str(chat_id).startswith("-"):
            self.blacklisted.append(chat_id)
            return await self.cache.update_one(
                {"_id": "bl_chats"}, {"$addToSet": {"chat_ids": chat_id}}, upsert=True
            )
        await self.cache.update_one(
            {"_id": "bl_users"}, {"$addToSet": {"user_ids": chat_id}}, upsert=True
        )

    async def del_blacklist(self, chat_id: int) -> None:
        if str(chat_id).startswith("-"):
            self.blacklisted.remove(chat_id)
            return await self.cache.update_one(
                {"_id": "bl_chats"},
                {"$pull": {"chat_ids": chat_id}},
            )
        await self.cache.update_one(
            {"_id": "bl_users"},
            {"$pull": {"user_ids": chat_id}},
        )

    async def get_blacklisted(self, chat: bool = False) -> list[int]:
        if chat:
            if not self.blacklisted:
                doc = await self.cache.find_one({"_id": "bl_chats"})
                self.blacklisted.extend(doc.get("chat_ids", []) if doc else [])
            return self.blacklisted
        doc = await self.cache.find_one({"_id": "bl_users"})
        return doc.get("user_ids", []) if doc else []

    # CHAT METHODS
    async def is_chat(self, chat_id: int) -> bool:
        return chat_id in self.chats

    async def add_chat(self, chat_id: int) -> None:
        if not await self.is_chat(chat_id):
            self.chats.append(chat_id)
            await self.chatsdb.insert_one({"_id": chat_id})

    async def rm_chat(self, chat_id: int) -> None:
        if await self.is_chat(chat_id):
            self.chats.remove(chat_id)
            await self.chatsdb.delete_one({"_id": chat_id})

    async def get_chats(self) -> list:
        if not self.chats:
            self.chats.extend([chat["_id"] async for chat in self.chatsdb.find()])
        return self.chats

    # LANGUAGE METHODS
    async def set_lang(self, chat_id: int, lang_code: str):
        await self.langdb.update_one(
            {"_id": chat_id},
            {"$set": {"lang": lang_code}},
            upsert=True,
        )
        self.lang[chat_id] = lang_code

    async def get_lang(self, chat_id: int) -> str:
        if chat_id not in self.lang:
            doc = await self.langdb.find_one({"_id": chat_id})
            self.lang[chat_id] = doc["lang"] if doc else "ar"
        return self.lang[chat_id]

    # MAINTENANCE MODE METHODS
    async def set_maintenance(self, status: bool) -> None:
        """Enable or disable maintenance mode."""
        await self.cache.update_one(
            {"_id": "maintenance"},
            {"$set": {"status": status}},
            upsert=True,
        )
        self.maintenance = status

    async def get_maintenance(self) -> bool:
        """Check if maintenance mode is enabled."""
        if not hasattr(self, 'maintenance'):
            doc = await self.cache.find_one({"_id": "maintenance"})
            self.maintenance = doc.get("status", False) if doc else False
        return self.maintenance

    # VPLAY TOGGLE METHODS
    async def get_vplay_enabled(self) -> bool:
        """Check if /vplay commands are enabled."""
        if hasattr(self, "vplay_enabled"):
            return self.vplay_enabled

        doc = await self.cache.find_one({"_id": "vplay_toggle"})
        self.vplay_enabled = doc.get("enabled", config.VIDEO_PLAY) if doc else config.VIDEO_PLAY
        return self.vplay_enabled

    async def set_vplay_enabled(self, enabled: bool) -> None:
        """Enable or disable /vplay commands globally."""
        self.vplay_enabled = enabled
        await self.cache.update_one(
            {"_id": "vplay_toggle"},
            {"$set": {"enabled": enabled}},
            upsert=True,
        )

    # GLOBAL BAN METHODS
    async def add_gban(self, user_id: int) -> None:
        """Add user to global ban list."""
        await self.cache.update_one(
            {"_id": "gbanned_users"},
            {"$addToSet": {"user_ids": user_id}},
            upsert=True,
        )
        if not hasattr(self, 'gbanned_users'):
            self.gbanned_users = []
        if user_id not in self.gbanned_users:
            self.gbanned_users.append(user_id)

    async def del_gban(self, user_id: int) -> None:
        """Remove user from global ban list."""
        await self.cache.update_one(
            {"_id": "gbanned_users"},
            {"$pull": {"user_ids": user_id}},
        )
        if hasattr(self, 'gbanned_users') and user_id in self.gbanned_users:
            self.gbanned_users.remove(user_id)

    async def get_gbanned(self) -> list[int]:
        """Get list of globally banned users."""
        if not hasattr(self, 'gbanned_users'):
            doc = await self.cache.find_one({"_id": "gbanned_users"})
            self.gbanned_users = doc.get("user_ids", []) if doc else []
        return self.gbanned_users
    
    async def is_gbanned(self, user_id: int) -> bool:
        """Check if user is globally banned."""
        gbanned = await self.get_gbanned()
        return user_id in gbanned

    # LOGGER METHODS
    async def is_logger(self) -> bool:
        return self.logger

    async def get_logger(self) -> bool:
        doc = await self.cache.find_one({"_id": "logger"})
        if doc:
            self.logger = doc["status"]
        return self.logger

    async def set_logger(self, status: bool) -> None:
        self.logger = status
        await self.cache.update_one(
            {"_id": "logger"},
            {"$set": {"status": status}},
            upsert=True,
        )

    # CHANNEL PLAY METHODS
    async def get_cmode(self, chat_id: int) -> int | None:
        """Get channel play mode for a chat."""
        doc = await self.cache.find_one({"_id": f"cplay_{chat_id}"})
        return doc.get("channel_id") if doc else None

    async def set_cmode(self, chat_id: int, channel_id: int | None) -> None:
        """Set or remove channel play mode for a chat."""
        if channel_id is None:
            await self.cache.delete_one({"_id": f"cplay_{chat_id}"})
        else:
            await self.cache.update_one(
                {"_id": f"cplay_{chat_id}"},
                {"$set": {"channel_id": channel_id}},
                upsert=True,
            )
    
    async def get_group_for_channel(self, channel_id: int) -> int | None:
        """Reverse lookup: Find which group has this channel set for channel play.
        
        When audio streams to a channel, we need to know which group initiated it
        so we can send control messages to the group instead of the channel.
        """
        doc = await self.cache.find_one({"channel_id": channel_id})
        if doc and doc.get("_id", "").startswith("cplay_"):
            group_id_str = doc["_id"].replace("cplay_", "")
            try:
                return int(group_id_str)
            except ValueError:
                return None
        return None

    # AUTO LEAVE METHODS
    async def get_autoleave(self, chat_id: int) -> bool:
        """Get auto-leave status for a chat. Default is False."""
        doc = await self.cache.find_one({"_id": f"autoleave_{chat_id}"})
        return doc.get("enabled", False) if doc else False

    async def set_autoleave(self, chat_id: int, enabled: bool) -> None:
        """Enable or disable auto-leave for a chat."""
        await self.cache.update_one(
            {"_id": f"autoleave_{chat_id}"},
            {"$set": {"enabled": enabled}},
            upsert=True,
        )

    # AUTO END METHODS
    # NOTE: intentionally uses its own "autoend_{chat_id}" cache key, separate
    # from "autoleave_{chat_id}" above, so the two features never share state.
    async def get_autoend(self, chat_id: int) -> bool:
        """Get auto-end status for a chat. Default is False."""
        doc = await self.cache.find_one({"_id": f"autoend_{chat_id}"})
        return doc.get("enabled", False) if doc else False

    async def set_autoend(self, chat_id: int, enabled: bool) -> None:
        """Enable or disable auto-end for a chat."""
        await self.cache.update_one(
            {"_id": f"autoend_{chat_id}"},
            {"$set": {"enabled": enabled}},
            upsert=True,
        )

    # LOOP MODE METHODS
    async def get_loop(self, chat_id: int) -> int:
        """Get loop mode for a chat. 0=off, 1=single, 10=queue"""
        doc = await self.cache.find_one({"_id": f"loop_{chat_id}"})
        return doc.get("mode", 0) if doc else 0

    async def set_loop(self, chat_id: int, mode: int) -> None:
        """Set loop mode for a chat."""
        if mode == 0:
            await self.cache.delete_one({"_id": f"loop_{chat_id}"})
        else:
            await self.cache.update_one(
                {"_id": f"loop_{chat_id}"},
                {"$set": {"mode": mode}},
                upsert=True,
            )

    # PLAY MODE METHODS
    async def get_play_mode(self, chat_id: int) -> bool:
        if chat_id not in self.play_mode:
            doc = await self.playmodedb.find_one({"_id": chat_id})
            if doc:
                self.play_mode.append(chat_id)
        return chat_id in self.play_mode

    async def set_play_mode(self, chat_id: int, remove: bool = False) -> None:
        if remove:
            if chat_id in self.play_mode:
                self.play_mode.remove(chat_id)
            await self.playmodedb.delete_one({"_id": chat_id})
        else:
            if chat_id not in self.play_mode:
                self.play_mode.append(chat_id)
            await self.playmodedb.update_one(
                {"_id": chat_id}, {"$set": {"_id": chat_id}}, upsert=True
            )

    # SUDO METHODS
    async def add_sudo(self, user_id: int) -> None:
        await self.cache.update_one(
            {"_id": "sudoers"}, {"$addToSet": {"user_ids": user_id}}, upsert=True
        )

    async def del_sudo(self, user_id: int) -> None:
        await self.cache.update_one(
            {"_id": "sudoers"}, {"$pull": {"user_ids": user_id}}
        )

    async def get_sudoers(self) -> list[int]:
        doc = await self.cache.find_one({"_id": "sudoers"})
        return doc.get("user_ids", []) if doc else []

    # USER METHODS
    async def is_user(self, user_id: int) -> bool:
        return user_id in self.users

    async def add_user(self, user_id: int) -> None:
        if not await self.is_user(user_id):
            self.users.append(user_id)
            await self.usersdb.insert_one({"_id": user_id})

    async def rm_user(self, user_id: int) -> None:
        if await self.is_user(user_id):
            self.users.remove(user_id)
            await self.usersdb.delete_one({"_id": user_id})

    async def get_users(self) -> list:
        if not self.users:
            self.users.extend([user["_id"] async for user in self.usersdb.find()])
        return self.users

    async def migrate_coll(self) -> None:
        """Migrate old collection structure (ObjectId) to new structure (int)."""
        from bson import ObjectId
        logger.info("🔄 Migrating users and chats from old collections...")

        musers, mchats, done = [], [], []
        
        # Collect all users from both old and new collections
        try:
            ulist = [user async for user in self.db.tgusersdb.find()]
        except Exception:
            ulist = []
        
        try:
            ulist.extend([user async for user in self.usersdb.find()])
        except Exception:
            pass

        # Process users
        for user in ulist:
            try:
                if isinstance(user.get("_id"), ObjectId):
                    user_id = int(user.get("user_id", 0))
                    if user_id and user_id not in done:
                        done.append(user_id)
                        musers.append({"_id": user_id})
                else:
                    user_id = int(user["_id"])
                    if user_id not in done:
                        done.append(user_id)
                        musers.append({"_id": user_id})
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping invalid user entry: {e}")
                continue
        
        # Drop old collections and insert migrated users
        try:
            await self.usersdb.drop()
        except Exception:
            pass
        try:
            await self.db.tgusersdb.drop()
        except Exception:
            pass
        if musers:
            try:
                await self.usersdb.insert_many(musers, ordered=False)
            except Exception as e:
                logger.debug(f"User migration bulk insert error (may be duplicate keys): {e}")

        # Process chats
        done.clear()
        try:
            async for chat in self.chatsdb.find():
                try:
                    if isinstance(chat.get("_id"), ObjectId):
                        chat_id = int(chat.get("chat_id", 0))
                        if chat_id and chat_id not in done:
                            done.append(chat_id)
                            mchats.append({"_id": chat_id})
                    else:
                        chat_id = int(chat["_id"])
                        if chat_id not in done:
                            done.append(chat_id)
                            mchats.append({"_id": chat_id})
                except (ValueError, KeyError) as e:
                    logger.debug(f"Skipping invalid chat entry: {e}")
                    continue
        except Exception as e:
            logger.debug(f"Error reading chats collection: {e}")
        
        # Drop old collection and insert migrated chats
        try:
            await self.chatsdb.drop()
        except Exception:
            pass
        if mchats:
            try:
                await self.chatsdb.insert_many(mchats, ordered=False)
            except Exception as e:
                logger.debug(f"Chat migration bulk insert error (may be duplicate keys): {e}")

        # Mark migration as complete
        await self.cache.update_one(
            {"_id": "migrated"},
            {"$set": {"status": True, "timestamp": time()}},
            upsert=True
        )
        logger.info("✅ Migration completed successfully.")

    async def load_cache(self) -> None:
        """Preload cache data from database for faster access."""
        # Check if migration needed
        doc = await self.cache.find_one({"_id": "migrated"})
        if not doc:
            await self.migrate_coll()

        # Preload all cache data
        logger.info("📦 Loading database cache...")
        
        # Load chats, users, blacklists, and logger status
        await self.get_chats()
        await self.get_users()
        await self.get_blacklisted(chat=True)  # Load blacklisted chats
        await self.get_logger()

        # Load persisted runtime state directly from the DB so it survives
        # restarts. These attributes are pre-initialised with defaults in
        # __init__, which makes the lazy `hasattr` checks in their getters
        # always short-circuit before reading the DB. Loading them here keeps
        # maintenance mode, the /vplay toggle and the global-ban list intact
        # across restarts.
        maintenance_doc = await self.cache.find_one({"_id": "maintenance"})
        self.maintenance = maintenance_doc.get("status", False) if maintenance_doc else False

        vplay_doc = await self.cache.find_one({"_id": "vplay_toggle"})
        self.vplay_enabled = (
            vplay_doc.get("enabled", config.VIDEO_PLAY) if vplay_doc else config.VIDEO_PLAY
        )

        gban_doc = await self.cache.find_one({"_id": "gbanned_users"})
        self.gbanned_users = gban_doc.get("user_ids", []) if gban_doc else []

        # Preload sudoers list
        await self.get_sudoers()
        
        logger.info(f"✅ Cache loaded: {len(self.chats)} chats, {len(self.users)} users, {len(self.blacklisted)} blacklisted.")

    # ============================================================
    # AUDIO BITRATE METHODS
    # ============================================================
    async def get_audio_bitrate(self, chat_id: int) -> str:
        """Get audio bitrate setting for a chat."""
        doc = await self.cache.find_one({"_id": f"audio_bitrate_{chat_id}"})
        return doc.get("bitrate", "128k") if doc else "128k"

    async def set_audio_bitrate(self, chat_id: int, bitrate: str) -> None:
        """Set audio bitrate setting for a chat."""
        await self.cache.update_one(
            {"_id": f"audio_bitrate_{chat_id}"},
            {"$set": {"bitrate": bitrate}},
            upsert=True,
        )

    # ============================================================
    # VIDEO QUALITY METHODS
    # ============================================================
    async def get_video_quality(self, chat_id: int) -> str:
        """Get video quality setting for a chat."""
        doc = await self.cache.find_one({"_id": f"video_quality_{chat_id}"})
        return doc.get("quality", "720") if doc else "720"

    async def set_video_quality(self, chat_id: int, quality: str) -> None:
        """Set video quality setting for a chat."""
        await self.cache.update_one(
            {"_id": f"video_quality_{chat_id}"},
            {"$set": {"quality": quality}},
            upsert=True,
        )

    # ============================================================
    # TOP TRACKS METHODS
    # ============================================================
    async def increment_track(self, vidid: str, chat_id: int, user_id: int) -> None:
        """Increment play count for a track globally, per chat, and per user."""
        # Global counter
        await self.db.top_global.update_one(
            {"_id": vidid},
            {"$inc": {"count": 1}},
            upsert=True,
        )
        # Per-chat counter
        await self.db.top_chats.update_one(
            {"_id": f"{chat_id}_{vidid}"},
            {"$inc": {"count": 1}, "$set": {"chat_id": chat_id, "vidid": vidid}},
            upsert=True,
        )
        # Per-user counter
        await self.db.top_users.update_one(
            {"_id": f"{user_id}_{vidid}"},
            {"$inc": {"count": 1}, "$set": {"user_id": user_id, "vidid": vidid}},
            upsert=True,
        )

    async def get_global_tops(self) -> dict:
        """Get top 10 tracks globally by play count."""
        cursor = self.db.top_global.find().sort("count", -1).limit(10)
        return {doc["_id"]: doc["count"] async for doc in cursor}

    async def get_chat_tops(self, chat_id: int) -> dict:
        """Get top 10 tracks in a specific chat."""
        cursor = self.db.top_chats.find({"chat_id": chat_id}).sort("count", -1).limit(10)
        return {doc["vidid"]: doc["count"] async for doc in cursor}

    async def get_user_tops(self, user_id: int) -> dict:
        """Get top 10 tracks for a specific user."""
        cursor = self.db.top_users.find({"user_id": user_id}).sort("count", -1).limit(10)
        return {doc["vidid"]: doc["count"] async for doc in cursor}

    # ============================================================
    # CLEAN MODE METHODS
    # ============================================================
    async def is_cleanmode_on(self, chat_id: int) -> bool:
        """Check if clean mode is enabled for a chat."""
        doc = await self.cache.find_one({"_id": f"cleanmode_{chat_id}"})
        return doc.get("enabled", False) if doc else False

    async def cleanmode_on(self, chat_id: int) -> None:
        """Enable clean mode for a chat."""
        await self.cache.update_one(
            {"_id": f"cleanmode_{chat_id}"},
            {"$set": {"enabled": True}},
            upsert=True,
        )

    async def cleanmode_off(self, chat_id: int) -> None:
        """Disable clean mode for a chat."""
        await self.cache.update_one(
            {"_id": f"cleanmode_{chat_id}"},
            {"$set": {"enabled": False}},
            upsert=True,
        )
