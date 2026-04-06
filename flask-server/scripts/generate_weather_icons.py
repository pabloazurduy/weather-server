#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from weather_icons import save_weather_icons


def main():
    output_dir = ROOT / "img" / "weather-icons"
    save_weather_icons(output_dir, size=128)
    print(output_dir)


if __name__ == "__main__":
    main()