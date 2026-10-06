# Genie video ad

The ad is a 29.6-second, 1280×720 MP4 with H.264 video and AAC audio.
It introduces Genie, previews a listening-port wish on Linux and Windows,
shows the expanded built-ins, illustrates cancelling a service restart, and
ends with the repository URL. The scenes are illustrative previews, not
recordings of changes made to a Windows or Linux host. The Linux/Windows
commands shown were checked against `offline_match`.

`promo.html` is self-contained: no remote fonts or media. `record.js` captures
it in Chromium and writes the animation's sound events. `generate_audio.py`
synthesizes the music and effects with NumPy; no third-party audio samples are
used. The CLI itself remains dependency-free.

## Reproduce in this prepared workspace

From `/workspace/genie`, using the environment's existing Node, Playwright,
Chromium, NumPy and FFmpeg installations:

```bash
PLAYWRIGHT_BROWSERS_PATH=/workspace/.cache/genie-playwright \
GENIE_CHROMIUM=/usr/bin/chromium node record.js
python3 generate_audio.py 29.6 rec
ffmpeg -hide_banner -loglevel error -y \
  -i rec/genie-ad.webm -i rec/audio.wav \
  -c:v libx264 -preset medium -crf 19 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -shortest -movflags +faststart rec/genie-ad.mp4
```

Playwright's FFmpeg cache entry is a symlink to the installed `/usr/bin/ffmpeg`
in `/workspace/.cache/genie-playwright/ffmpeg-1011/ffmpeg-linux`. This uses the
existing trusted system binary rather than downloading an extra copy. On
another machine, install Playwright's Chromium and FFmpeg through its standard
installer (`npx playwright install chromium ffmpeg`) and omit those environment
variables, or set `GENIE_CHROMIUM` to your installed Chromium executable.
Playwright and NumPy are media development tools, not Genie runtime dependencies.

Outputs are ignored under `rec/`: `genie-ad.mp4`, source `genie-ad.webm`,
`events.json`, synthesized `audio.wav`, and `poster.png`. The MP4 was decoded
successfully and its H.264/AAC streams, 720p resolution, and duration verified.
Selected Linux and Windows frames were visually inspected for readability.
