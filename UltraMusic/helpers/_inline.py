# ==============================================================================
# _inline.py - Inline Keyboard Button Builder
# ==============================================================================
# This file provides helper functions to create inline keyboard buttons.
# Used to build:
# - Playback control buttons (play, pause, skip, stop, etc.)
# - Language selection menus
# - Help menus and navigation
# - Download cancel buttons
# - Settings buttons
# ==============================================================================

from pyrogram import types

from UltraMusic import app, config, lang



class Inline:
    def __init__(self):
        self.ikm = types.InlineKeyboardMarkup
        self.ikb = types.InlineKeyboardButton

    def cancel_dl(self, text) -> types.InlineKeyboardMarkup:
        return self.ikm([[self.ikb(text=text, callback_data=f"cancel_dl")]])

    def _developer_url(self) -> str:
        """Build the URL for the "تواصل مع المطور" button.

        Prefers a public username (https://t.me/USERNAME) when OWNER_USERNAME is
        set, otherwise falls back to a direct profile link via OWNER_ID.
        """
        if getattr(config, "OWNER_USERNAME", ""):
            return f"https://t.me/{config.OWNER_USERNAME}"
        return f"tg://user?id={config.OWNER_ID}"

    def controls(
        self,
        chat_id: int,
        status: str = None,
        timer: str = None,
        remove: bool = False,
        is_live: bool = False,
        playing: bool = True,
        show_extra: bool = True,
        queue_toggle: bool = False,
    ) -> types.InlineKeyboardMarkup:
        """Build the unified playback-controls keyboard.

        This single function replaces the old controls() / play_queued() /
        queue_markup() trio - same callback_data scheme ("controls {action}
        {chat_id}") for every button, just different rows shown depending on
        the arguments passed in.

        Args:
            chat_id: Target chat id, embedded in every callback_data.
            status: Optional status/progress text shown as a full-width
                top row (e.g. "البث متوقف مؤقتاً"). Takes priority over timer.
            timer: Optional progress-bar text shown as a full-width top row
                when status is not given (used during live playback updates).
            remove: When True, only the status/timer row is shown (used to
                shrink the keyboard down after stop/auto-leave).
            is_live: When True, hides the percentage-seek row (seeking is not
                supported on live streams).
            playing: Current play state - controls whether the toggle button
                shows ⏸️ (currently playing → tap to pause) or ▶️ (currently
                paused → tap to resume).
            show_extra: When False, hides the secondary row (loop/shuffle/
                queue) - e.g. for the compact "now queued" notice.
            queue_toggle: When True, the single resume/pause toggle button
                appends a trailing "q" marker to its callback_data (replaces
                the old queue_markup() single-button toggle used inside the
                /queue display message).
        """
        keyboard = []

        if status:
            keyboard.append(
                [self.ikb(
                    text=status, callback_data=f"controls status {chat_id}")]
            )
        elif timer:
            keyboard.append(
                [self.ikb(
                    text=timer, callback_data=f"controls status {chat_id}")]
            )

        if not remove:
            toggle_action = "pause" if playing else "resume"
            toggle_icon = "⏸️" if playing else "▶️"
            toggle_data = f"controls {toggle_action} {chat_id}"
            if queue_toggle:
                toggle_data += " q"

            # Row 1 - primary controls (always shown)
            keyboard.append(
                [
                    self.ikb(
                        text="⏪10", callback_data=f"controls seek_back_10 {chat_id}"),
                    self.ikb(text=toggle_icon, callback_data=toggle_data),
                    self.ikb(
                        text="⏩10", callback_data=f"controls seek_forward_10 {chat_id}"),
                    self.ikb(
                        text="⏭️", callback_data=f"controls skip {chat_id}"),
                    self.ikb(
                        text="⏹️", callback_data=f"controls stop {chat_id}"),
                ]
            )

            # Row 2 - secondary controls (loop / shuffle / queue)
            if show_extra:
                keyboard.append(
                    [
                        self.ikb(
                            text="🔁", callback_data=f"controls loop {chat_id}"),
                        self.ikb(
                            text="🔀", callback_data=f"controls shuffle {chat_id}"),
                        self.ikb(
                            text="📃", callback_data=f"controls show_queue {chat_id}"),
                    ]
                )

            # Row 3 - delete button, full width
            keyboard.append(
                [
                    self.ikb(
                        text="🗑️", callback_data=f"controls close {chat_id}"),
                ]
            )

            # Volume row (kept as-is, unrelated to this redesign's 3 rows)
            keyboard.append([
                self.ikb(text="🔉", callback_data=f"controls vol_down {chat_id}"),
                self.ikb(text="🔊", callback_data=f"controls vol_up {chat_id}"),
            ])

        if not remove and not is_live:
            keyboard.append([
                self.ikb(text="◀ 25%", callback_data=f"controls seekp_25 {chat_id}"),
                self.ikb(text="⏸ 50%", callback_data=f"controls seekp_50 {chat_id}"),
                self.ikb(text="75% ▶", callback_data=f"controls seekp_75 {chat_id}"),
            ])
        return self.ikm(keyboard)

    def help_markup(
        self, _lang: dict, back: bool = False
    ) -> types.InlineKeyboardMarkup:
        """Create help menu with categorized buttons."""
        if back:
            rows = [
                [
                    self.ikb(text="ʙᴀᴄᴋ", callback_data="help_main"),
                ]
            ]
        else:
            # Help menu with categorized buttons (3 per row)
            rows = [
                [
                    self.ikb(text="ᴀᴅᴍɪɴꜱ", callback_data="help_admins"),
                    self.ikb(text="ᴀᴜᴛʜ", callback_data="help_auth"),
                    self.ikb(text="ʙʀᴏᴀᴅᴄᴀꜱᴛ", callback_data="help_broadcast"),
                ],
                [
                    self.ikb(text="ʙʟ-ᴄʜᴀᴛ", callback_data="help_blchat"),
                    self.ikb(text="ʙʟ-ᴜꜱᴇʀ", callback_data="help_bluser"),
                    self.ikb(text="ɢ-ʙᴀɴ", callback_data="help_gban"),
                ],
                [
                    self.ikb(text="ʟᴏᴏᴘ", callback_data="help_loop"),
                    self.ikb(text="ᴘʟᴀʏ", callback_data="help_play"),
                    self.ikb(text="ǫᴜᴇᴜᴇ", callback_data="help_queue"),
                ],
                [
                    self.ikb(text="ꜱᴇᴇᴋ", callback_data="help_seek"),
                    self.ikb(text="ꜱʜᴜꜰꜰʟᴇ", callback_data="help_shuffle"),
                    self.ikb(text="ᴘɪɴɢ", callback_data="help_ping"),
                ],
                [
                    self.ikb(text="ꜱᴛᴀᴛꜱ", callback_data="help_stats"),
                    self.ikb(text="ꜱᴜᴅᴏ", callback_data="help_sudo"),
                    self.ikb(text="ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ", callback_data="help_maintenance"),
                ],
                [
                    self.ikb(text="ʙᴀᴄᴋ", callback_data="start"),
                ]
            ]
        return self.ikm(rows)


    def ping_markup(self, text: str) -> types.InlineKeyboardMarkup:
        return self.ikm([
            [
                self.ikb(text="📢 Channel", url=config.SUPPORT_CHANNEL),
                self.ikb(text="🆘 Support", url=config.SUPPORT_CHAT),
            ],
            [
                self.ikb(text="➕ Add Me to Your Group", url=f"https://t.me/{app.username}?startgroup=true"),
            ]
        ])

    def settings_markup(
        self, lang: dict, admin_only: bool, language: str, chat_id: int
    ) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [
                [
                    self.ikb(
                        text=lang["play_mode"] + " ➜",
                        callback_data=f"controls status {chat_id}",
                    ),
                    self.ikb(text=admin_only, callback_data="playmode"),
                ],
            ]
        )

    def start_key(
        self, lang: dict, private: bool = False
    ) -> types.InlineKeyboardMarkup:
        rows = [
            [
                self.ikb(
                    text=lang["add_me"],
                    url=f"https://t.me/{app.username}?startgroup=true",
                )
            ],
            [self.ikb(text=lang["help"], callback_data="help")],
            [
                self.ikb(text=lang["support"], url=config.SUPPORT_CHAT),
                self.ikb(text=lang["channel"], url=config.SUPPORT_CHANNEL),
            ],
            [self.ikb(text="📩 تواصل مع المطور", url=self._developer_url())],
        ]
        return self.ikm(rows)

    def yt_key(self, link: str) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [
                [
                    self.ikb(text="ᴄᴏᴘʏ ʟɪɴᴋ", copy_text=link),
                    self.ikb(text="ᴏᴘᴇɴ ɪɴ ʏᴏᴜᴛᴜʙᴇ", url=link),
                ],
            ]
        )
