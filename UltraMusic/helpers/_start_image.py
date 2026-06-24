# ==============================================================================
# _start_image.py - Local /start Welcome Image Generator
# ==============================================================================
# Generates a welcome image entirely with PIL (no network call, no external
# album-art image needed) so the bot can show a /start photo without relying
# on the external START_IMG link in config.py.
#
# Visually matches the "now playing" thumbnail engine in _thumbnails.py:
# - Same frosted glass panel (same TRANSPARENCY, same rounded-corner style)
# - Same Raleway-Bold / Inter-Light fonts
# The background is a simple two-color PIL gradient instead of blurred album
# art, since there is no track image to draw from on /start.
#
# Safety: every public entry point follows the same try/except philosophy as
# _thumbnails.py — on any failure this returns None (never raises) so the
# caller (plugins/information/start.py) can fall back to config.START_IMG.
# ==============================================================================

import asyncio
import os

from PIL import Image, ImageDraw, ImageFont

from UltraMusic.helpers._thumbnails import PANEL_W, PANEL_H, PANEL_X, PANEL_Y, TRANSPARENCY

# IMPORTANT — Arabic text limitation:
# Neither shipped font (Raleway-Bold.ttf, Inter-Light.ttf) contains Arabic
# glyphs, and PIL's ImageDraw.text() does not shape Arabic (no ligatures/RTL
# reordering) even when a font does have the glyphs. Baking Arabic text into
# this raster image would render as broken boxes (verified while building
# this module). The actual Arabic welcome copy already lives correctly in
# locales/ar.json (start_pm), rendered as a normal Telegram caption — which
# is the right place for it, since Telegram shapes RTL text natively.
# This generator therefore only draws Latin text (the bot name, and an
# optional short Latin byline) onto the image itself.
CANVAS_W, CANVAS_H = 1280, 720

# Gradient endpoints — a calm dark-blue-to-purple sweep that keeps the white
# panel text and the black panel text both legible without needing album art.
GRADIENT_TOP = (24, 28, 58)
GRADIENT_BOTTOM = (66, 36, 90)

TITLE_FONT_SIZE = 54
TAGLINE_FONT_SIZE = 22

OUTPUT_PATH = "cache/start_image_generated.png"


def _make_gradient_background() -> Image.Image:
    """Simple vertical two-color gradient, pure PIL, no extra dependencies."""
    bg = Image.new("RGB", (CANVAS_W, CANVAS_H))
    draw = ImageDraw.Draw(bg)
    for y in range(CANVAS_H):
        t = y / max(CANVAS_H - 1, 1)
        r = int(GRADIENT_TOP[0] + (GRADIENT_BOTTOM[0] - GRADIENT_TOP[0]) * t)
        g = int(GRADIENT_TOP[1] + (GRADIENT_BOTTOM[1] - GRADIENT_TOP[1]) * t)
        b = int(GRADIENT_TOP[2] + (GRADIENT_BOTTOM[2] - GRADIENT_TOP[2]) * t)
        draw.line([(0, y), (CANVAS_W, y)], fill=(r, g, b))
    return bg.convert("RGBA")


class StartImage:
    def __init__(self):
        try:
            self.title_font = ImageFont.truetype(
                "UltraMusic/helpers/Raleway-Bold.ttf", TITLE_FONT_SIZE)
            self.tagline_font = ImageFont.truetype(
                "UltraMusic/helpers/Inter-Light.ttf", TAGLINE_FONT_SIZE)
        except OSError:
            self.title_font = self.tagline_font = ImageFont.load_default()

    async def generate(self, bot_name: str, byline: str = "Advanced Telegram Music Bot") -> str | None:
        """Generate (or reuse the cached) local welcome image.

        `byline` must be Latin text — see the Arabic-limitation note above.
        Returns the output path on success, or None on any failure so the
        caller can fall back to config.START_IMG.
        """
        try:
            if os.path.exists(OUTPUT_PATH):
                return OUTPUT_PATH
            return await asyncio.get_event_loop().run_in_executor(
                None, self._generate_sync, bot_name, byline
            )
        except Exception:
            return None

    def _generate_sync(self, bot_name: str, byline: str) -> str | None:
        """Synchronous PIL drawing — runs in thread pool, mirrors _thumbnails.py."""
        try:
            bg = _make_gradient_background()

            # Frosted glass panel — identical recipe to _thumbnails.py so the
            # welcome image reads as part of the same visual identity.
            panel_area = bg.crop(
                (PANEL_X, PANEL_Y, PANEL_X + PANEL_W, PANEL_Y + PANEL_H))
            overlay = Image.new("RGBA", (PANEL_W, PANEL_H),
                                (255, 255, 255, TRANSPARENCY))
            frosted = Image.alpha_composite(panel_area, overlay)

            mask = Image.new("L", (PANEL_W, PANEL_H), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, PANEL_W, PANEL_H), 50, fill=255)
            bg.paste(frosted, (PANEL_X, PANEL_Y), mask)

            draw = ImageDraw.Draw(bg)

            # Bot name — centered title, same bold font as track titles.
            title_w = draw.textlength(bot_name, font=self.title_font)
            title_x = PANEL_X + (PANEL_W - title_w) // 2
            title_y = PANEL_Y + (PANEL_H // 2) - 50
            draw.text((title_x, title_y), bot_name,
                      fill="black", font=self.title_font)

            # Optional short Latin byline below the title, same light font
            # used for metadata text elsewhere — Latin-only, see module note.
            if byline:
                byline_w = draw.textlength(byline, font=self.tagline_font)
                byline_x = PANEL_X + (PANEL_W - byline_w) // 2
                byline_y = title_y + TITLE_FONT_SIZE + 24
                draw.text((byline_x, byline_y), byline,
                          fill="black", font=self.tagline_font)

            os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
            bg.convert("RGB").save(OUTPUT_PATH)
            return OUTPUT_PATH
        except Exception:
            return None


start_image = StartImage()
