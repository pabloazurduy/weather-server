#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


DEFAULT_ICON_NAMES = [
    "sunny_warm",
    "sunny_cold",
    "rainy_warm",
    "rainy_cold",
    "cloudy_warm",
    "cloudy_cold",
    "snow",
    "freezing_windy",
]


def split_character_grid(source_path: Path, output_dir: Path, rows: int, cols: int):
    output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as image:
        cell_w = image.width // cols
        cell_h = image.height // rows

        for index, icon_name in enumerate(DEFAULT_ICON_NAMES):
            row = index // cols
            col = index % cols
            left = col * cell_w
            top = row * cell_h
            right = image.width if col == cols - 1 else (col + 1) * cell_w
            bottom = image.height if row == rows - 1 else (row + 1) * cell_h
            tile = image.crop((left, top, right, bottom))
            tile.save(output_dir / f"{icon_name}.png")


def main():
    parser = argparse.ArgumentParser(description="Split a 2x4 character weather grid into named tiles.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--rows", type=int, default=2)
    parser.add_argument("--cols", type=int, default=4)
    args = parser.parse_args()
    split_character_grid(args.source, args.output_dir, args.rows, args.cols)


if __name__ == "__main__":
    main()