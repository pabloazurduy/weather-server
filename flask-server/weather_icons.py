from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw


ICON_KINDS = (
    "sun",
    "moon",
    "partly",
    "partly-night",
    "cloud",
    "fog",
    "rain",
    "snow",
    "storm",
)


def _stroke(size: int, factor: float = 0.06) -> int:
    return max(2, int(round(size * factor)))


def _cloud_box(size: int) -> tuple[int, int, int, int]:
    return (
        int(size * 0.14),
        int(size * 0.28),
        int(size * 0.86),
        int(size * 0.72),
    )


def _draw_sun(draw: ImageDraw.ImageDraw, size: int, center: tuple[int, int], radius: int):
    stroke = _stroke(size)
    cx, cy = center
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=0, width=stroke)
    for angle in range(0, 360, 45):
        inner = radius + stroke
        outer = radius + int(size * 0.12)
        x0 = cx + math.cos(math.radians(angle)) * inner
        y0 = cy + math.sin(math.radians(angle)) * inner
        x1 = cx + math.cos(math.radians(angle)) * outer
        y1 = cy + math.sin(math.radians(angle)) * outer
        draw.line([x0, y0, x1, y1], fill=0, width=max(1, stroke - 1))


def _draw_moon(icon: Image.Image, size: int, center: tuple[int, int], radius: int):
    draw = ImageDraw.Draw(icon)
    cx, cy = center
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=0)
    cutout_shift = int(radius * 0.45)
    draw.ellipse(
        [
            cx - radius + cutout_shift,
            cy - radius,
            cx + radius + cutout_shift,
            cy + radius,
        ],
        fill=255,
    )


def _draw_cloud(draw: ImageDraw.ImageDraw, size: int, offset_x: int = 0, offset_y: int = 0):
    left, top, right, bottom = _cloud_box(size)
    left += offset_x
    top += offset_y
    right += offset_x
    bottom += offset_y
    width = right - left
    height = bottom - top

    draw.ellipse(
        [
            left + int(width * 0.03),
            top + int(height * 0.28),
            left + int(width * 0.42),
            top + int(height * 0.82),
        ],
        fill=0,
    )
    draw.ellipse(
        [
            left + int(width * 0.24),
            top,
            left + int(width * 0.72),
            top + int(height * 0.72),
        ],
        fill=0,
    )
    draw.ellipse(
        [
            left + int(width * 0.56),
            top + int(height * 0.22),
            right,
            top + int(height * 0.78),
        ],
        fill=0,
    )
    draw.rounded_rectangle(
        [
            left + int(width * 0.12),
            top + int(height * 0.42),
            right - int(width * 0.08),
            bottom,
        ],
        radius=max(4, int(height * 0.22)),
        fill=0,
    )


def _draw_fog(draw: ImageDraw.ImageDraw, size: int):
    _draw_cloud(draw, size, offset_y=-6)
    stroke = max(1, _stroke(size, 0.035))
    y_positions = [int(size * 0.66), int(size * 0.76), int(size * 0.86)]
    for y in y_positions:
        draw.line([int(size * 0.16), y, int(size * 0.84), y], fill=0, width=stroke)


def _draw_rain(draw: ImageDraw.ImageDraw, size: int):
    _draw_cloud(draw, size, offset_y=-8)
    stroke = max(1, _stroke(size, 0.045))
    for x in (int(size * 0.28), int(size * 0.48), int(size * 0.68)):
        draw.line([x, int(size * 0.66), x - int(size * 0.05), int(size * 0.88)], fill=0, width=stroke)


def _draw_snow(draw: ImageDraw.ImageDraw, size: int):
    _draw_cloud(draw, size, offset_y=-10)
    stroke = max(1, _stroke(size, 0.03))
    centers = [(int(size * 0.36), int(size * 0.78)), (int(size * 0.62), int(size * 0.8))]
    arm = int(size * 0.07)
    for cx, cy in centers:
        draw.line([cx - arm, cy, cx + arm, cy], fill=0, width=stroke)
        draw.line([cx, cy - arm, cx, cy + arm], fill=0, width=stroke)
        draw.line([cx - arm, cy - arm, cx + arm, cy + arm], fill=0, width=stroke)
        draw.line([cx - arm, cy + arm, cx + arm, cy - arm], fill=0, width=stroke)


def _draw_storm(draw: ImageDraw.ImageDraw, size: int):
    _draw_cloud(draw, size, offset_y=-10)
    bolt = [
        (int(size * 0.48), int(size * 0.62)),
        (int(size * 0.38), int(size * 0.82)),
        (int(size * 0.5), int(size * 0.82)),
        (int(size * 0.44), int(size * 0.96)),
        (int(size * 0.66), int(size * 0.7)),
        (int(size * 0.54), int(size * 0.7)),
    ]
    draw.polygon(bolt, fill=0)


def render_weather_icon(kind: str, size: int = 96) -> Image.Image:
    icon = Image.new("L", (size, size), 255)
    draw = ImageDraw.Draw(icon)

    if kind == "sun":
        _draw_sun(draw, size, center=(size // 2, size // 2), radius=int(size * 0.2))
        return icon

    if kind == "moon":
        _draw_moon(icon, size, center=(size // 2, size // 2), radius=int(size * 0.22))
        return icon

    if kind == "partly":
        _draw_sun(draw, size, center=(int(size * 0.36), int(size * 0.36)), radius=int(size * 0.16))
        _draw_cloud(draw, size, offset_x=8, offset_y=8)
        return icon

    if kind == "partly-night":
        _draw_moon(icon, size, center=(int(size * 0.38), int(size * 0.38)), radius=int(size * 0.18))
        _draw_cloud(draw, size, offset_x=8, offset_y=8)
        return icon

    if kind == "cloud":
        _draw_cloud(draw, size)
        return icon

    if kind == "fog":
        _draw_fog(draw, size)
        return icon

    if kind == "rain":
        _draw_rain(draw, size)
        return icon

    if kind == "snow":
        _draw_snow(draw, size)
        return icon

    if kind == "storm":
        _draw_storm(draw, size)
        return icon

    _draw_cloud(draw, size)
    return icon


def save_weather_icons(output_dir: Path, size: int = 96):
    output_dir.mkdir(parents=True, exist_ok=True)
    for kind in ICON_KINDS:
        render_weather_icon(kind, size=size).save(output_dir / f"{kind}.png")