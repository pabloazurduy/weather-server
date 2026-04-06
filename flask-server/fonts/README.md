Bundled font assets for consistent dashboard rendering.

These files are committed so the plain Python server and the Docker image use the same typefaces and weather glyphs.

- `LiberationSans-Regular.ttf` and `LiberationSans-Bold.ttf` are the primary text fonts.
- `weathericons-regular-webfont.ttf` is the primary icon font for weather symbols.

`app.py` prefers these local files before any system font paths.