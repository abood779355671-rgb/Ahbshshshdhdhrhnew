# ==============================================================================
# _thumbnails.py - Dynamic Thumbnail Generator
# ==============================================================================
# This file generates beautiful custom thumbnails for now playing messages.
# Features:
# - Modern frosted glass design
# - Background blur effect with album art
# - Track title and metadata display
# - Progress bar visualization
# - Social media icons
# - Responsive text sizing
# - Image caching for performance
# - Non-blocking PIL operations (runs in thread executor)
# ==============================================================================

import os
import re
import asyncio
import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from UltraMusic import config
from UltraMusic.helpers import Track

# Modern frosted glass design constants
PANEL_W, PANEL_H = 763, 545
PANEL_X = (1280 - PANEL_W) // 2
PANEL_Y = 88
TRANSPARENCY = 170

THUMB_W, THUMB_H = 542, 273
THUMB_X = PANEL_X + (PANEL_W - THUMB_W) // 2
THUMB_Y = PANEL_Y + 36

TITLE_X = 377
TITLE_Y = THUMB_Y + THUMB_H + 10
META_Y = TITLE_Y + 45

BAR_X, BAR_Y = 388, META_Y + 45
BAR_RED_LEN = 280
BAR_TOTAL_LEN = 480

ICONS_W, ICONS_H = 415, 45
ICONS_X = PANEL_X + (PANEL_W - ICONS_W) // 2
ICONS_Y = BAR_Y + 48

MAX_TITLE_WIDTH = 580


def trim_to_width(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
    """Trim text to fit within max width, adding ellipsis if needed."""
    ellipsis = "…"
    if font.getlength(text) <= max_w:
        return text
    for i in range(len(text) - 1, 0, -1):
        if font.getlength(text[:i] + ellipsis) <= max_w:
            return text[:i] + ellipsis
    return ellipsis


# ==============================================================================
# get_dominant_color - Extract the most common color from album art
# ==============================================================================
# Downscales the image to a tiny 50x50 sample (cheap, no extra dependencies
# beyond PIL which is already required) then uses Image.quantize() to reduce
# the palette and pick the most frequent color. The raw dominant color is then
# nudged toward a usable mid-brightness range so it stays legible as a
# progress-bar fill against the panel's black text — pure black/near-black or
# pure white/near-white album art would otherwise produce an invisible bar.
# ==============================================================================
def get_dominant_color(img: Image.Image, fallback=(229, 9, 20)) -> tuple:
    """Extract a contrast-safe dominant color from an image. Never raises."""
    try:
        sample = img.convert("RGB").resize((50, 50))
        # Reduce to a small palette and read back the most common color.
        quantized = sample.quantize(colors=8, method=Image.FASTOCTREE)
        palette = quantized.getpalette()
        color_counts = quantized.getcolors()
        if not color_counts:
            return fallback
        color_counts.sort(reverse=True)  # most frequent first
        _, dominant_index = color_counts[0]
        r = palette[dominant_index * 3]
        g = palette[dominant_index * 3 + 1]
        b = palette[dominant_index * 3 + 2]

        # Guard against low-contrast extremes (too dark / too light against
        # the black text + light frosted panel) by clamping perceived
        # brightness into a comfortable band, preserving the original hue.
        brightness = (0.299 * r + 0.587 * g + 0.114 * b)
        if brightness < 100:
            # Too dark — lighten while keeping hue ratios.
            scale = 100 / max(brightness, 1)
            r, g, b = (min(255, int(c * scale)) for c in (r, g, b))
        elif brightness > 215:
            # Too light — darken while keeping hue ratios.
            scale = 215 / brightness
            r, g, b = (int(c * scale) for c in (r, g, b))

        return (int(r), int(g), int(b))
    except Exception:
        return fallback


class Thumbnail:
    def __init__(self):
        try:
            self.title_font = ImageFont.truetype(
                "UltraMusic/helpers/Raleway-Bold.ttf", 32)
            self.regular_font = ImageFont.truetype(
                "UltraMusic/helpers/Inter-Light.ttf", 18)
        except OSError:
            self.title_font = self.regular_font = ImageFont.load_default()

    async def save_thumb(self, output_path: str, url: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                with open(output_path, "wb") as f:
                    f.write(await resp.read())
            return output_path

    async def generate(self, song: Track, size=(1280, 720)) -> str:
        """Generate thumbnail - downloads async, PIL operations in thread pool"""
        try:
            temp = f"cache/temp_{song.id}.jpg"
            output = f"cache/{song.id}_modern.png"
            if os.path.exists(output):
                return output

            # Download thumbnail (async operation)
            await self.save_thumb(temp, song.thumbnail)
            
            # **PERFORMANCE FIX**: Run PIL operations in thread executor to avoid blocking event loop
            # This prevents lag when generating thumbnails for multiple groups simultaneously
            return await asyncio.get_event_loop().run_in_executor(
                None, self._generate_sync, temp, output, song, size
            )
        except Exception:
            return config.DEFAULT_THUMB

    def _generate_sync(self, temp: str, output: str, song: Track, size=(1280, 720)) -> str:
        """Synchronous PIL operations - runs in thread pool"""
        try:
            # Prepare base image
            with Image.open(temp) as temp_img:
                base = temp_img.resize(size).convert("RGBA")

            # Create blurred background
            bg = ImageEnhance.Brightness(base.filter(
                ImageFilter.BoxBlur(10))).enhance(0.6)

            # Create frosted glass panel
            panel_area = bg.crop(
                (PANEL_X, PANEL_Y, PANEL_X + PANEL_W, PANEL_Y + PANEL_H))
            overlay = Image.new("RGBA", (PANEL_W, PANEL_H),
                                (255, 255, 255, TRANSPARENCY))
            frosted = Image.alpha_composite(panel_area, overlay)

            # Apply rounded corners to panel
            mask = Image.new("L", (PANEL_W, PANEL_H), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, PANEL_W, PANEL_H), 50, fill=255)
            bg.paste(frosted, (PANEL_X, PANEL_Y), mask)

            # Add thumbnail with rounded corners
            thumb = base.resize((THUMB_W, THUMB_H))
            tmask = Image.new("L", thumb.size, 0)
            ImageDraw.Draw(tmask).rounded_rectangle(
                (0, 0, THUMB_W, THUMB_H), 20, fill=255)
            bg.paste(thumb, (THUMB_X, THUMB_Y), tmask)

            # Draw text elements
            draw = ImageDraw.Draw(bg)

            # Clean and display title
            clean_title = re.sub(r"\W+", " ", song.title).title()
            draw.text(
                (TITLE_X, TITLE_Y),
                trim_to_width(clean_title, self.title_font, MAX_TITLE_WIDTH),
                fill="black",
                font=self.title_font
            )

            # Metadata
            draw.text(
                (TITLE_X, META_Y),
                f"YouTube | {song.view_count or 'Unknown Views'}",
                fill="black",
                font=self.regular_font
            )

            # Progress bar — color is derived from the album art's dominant
            # color (contrast-checked in get_dominant_color) instead of a
            # fixed "red", so the bar visually matches each track's artwork.
            bar_color = get_dominant_color(base)
            draw.line([(BAR_X, BAR_Y), (BAR_X + BAR_RED_LEN, BAR_Y)],
                      fill=bar_color, width=6)
            draw.line([(BAR_X + BAR_RED_LEN, BAR_Y),
                      (BAR_X + BAR_TOTAL_LEN, BAR_Y)], fill="gray", width=5)

            # Soft drop shadow behind the progress dot — a slightly larger,
            # semi-transparent gray circle drawn first, then the solid dot on
            # top, using the same draw.ellipse call style already used here.
            dot_cx, dot_cy = BAR_X + BAR_RED_LEN, BAR_Y
            shadow_overlay = Image.new("RGBA", bg.size, (0, 0, 0, 0))
            ImageDraw.Draw(shadow_overlay).ellipse(
                [(dot_cx - 9, dot_cy - 9 + 2), (dot_cx + 9, dot_cy + 9 + 2)],
                fill=(60, 60, 60, 90))
            bg.alpha_composite(shadow_overlay)  # in-place; existing draw handle stays valid
            draw.ellipse([(dot_cx - 7, dot_cy - 7), (dot_cx + 7, dot_cy + 7)],
                         fill=bar_color)

            # Time labels
            draw.text((BAR_X, BAR_Y + 15), "00:00",
                      fill="black", font=self.regular_font)

            is_live = getattr(song, 'is_live', False)
            end_text = "Live" if is_live else song.duration
            draw.text(
                (BAR_X + BAR_TOTAL_LEN - (90 if is_live else 60), BAR_Y + 15),
                end_text,
                fill="red" if is_live else "black",
                font=self.regular_font
            )

            # Control icons (if available)
            icons_path = "UltraMusic/helpers/play_icons.png"
            if os.path.isfile(icons_path):
                with Image.open(icons_path) as icons_img:
                    ic = icons_img.resize((ICONS_W, ICONS_H)).convert("RGBA")
                    r, g, b, a = ic.split()
                    black_ic = Image.merge(
                        "RGBA", (r.point(lambda _: 0), g.point(lambda _: 0), b.point(lambda _: 0), a))
                    bg.paste(black_ic, (ICONS_X, ICONS_Y), black_ic)

            # Save and cleanup
            bg.save(output)
            try:
                os.remove(temp)
            except OSError:
                pass

            return output
        except Exception:
            return config.DEFAULT_THUMB
