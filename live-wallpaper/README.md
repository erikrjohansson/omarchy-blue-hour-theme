# Blue Hour - live wallpaper (rain on glass)

A seamless looping animated version of the static wallpaper
([`backgrounds/03-blue-hour-background.png`](../backgrounds/03-blue-hour-background.png)).
Mist drifts across the scene, the glass "breathes" slightly, and new droplets
slide down with lens refraction, a specular highlight and a faint wet trail.
The droplets already printed on the wallpaper stay in place.

| File | Description |
|---|---|
| [`blue-hour-rain.2560x1440.mp4`](blue-hour-rain.2560x1440.mp4) | 80 droplets, normal size |
| [`blue-hour-rain-small.2560x1440.mp4`](blue-hour-rain-small.2560x1440.mp4) | 110 droplets at 60 % size, different random seed |
| [`rain.py`](rain.py) | The generator used to render both |

Both clips are 2560x1440, 24 s, 30 fps, H.264 (yuv420p, CRF 18), about 22 MB,
no audio. The loop is seamless: every animated term is periodic in the clip
length, and droplets fade in/out at the cycle boundary.

## Use it on Omarchy

Omarchy renders the static wallpaper itself, so a video has to sit on top of it.
The [Motion Wallpaper](https://github.com/28allday/Motion-Wallpaper-Omarchy)
shell plugin does exactly that (muted looping video on the background layer,
auto-pause under fullscreen windows):

```sh
omarchy plugin add https://github.com/28allday/Motion-Wallpaper-Omarchy.git --enable
omarchy-shell motion-wallpaper playAll ~/path/to/blue-hour-rain.2560x1440.mp4
omarchy-shell motion-wallpaper stop        # back to the static wallpaper
```

(Any player that can put a looping video on the Wayland background layer, e.g.
`mpvpaper`, works as well.) A video wallpaper uses more power than a static
image, which is why it is not wired into the theme's `backgrounds/` folder.

## Regenerate / tweak with `rain.py`

Requirements: Python 3, `ffmpeg`, and `pip install -r requirements.txt`
(`numpy`, `opencv-python-headless`).

```sh
python -m venv venv && ./venv/bin/pip install -r requirements.txt

# normal version
./venv/bin/python rain.py ../backgrounds/03-blue-hour-background.png blue-hour-rain.2560x1440.mp4

# smaller drops (what the "small" clip uses)
./venv/bin/python rain.py ../backgrounds/03-blue-hour-background.png blue-hour-rain-small.2560x1440.mp4 \
    --size 0.6 --drops 110 --seed 11

# preview a single frame (seconds) instead of rendering a video
./venv/bin/python rain.py ../backgrounds/03-blue-hour-background.png frame.png --frame 6
```

| Option | Default | Meaning |
|---|---|---|
| `--seconds` | 24 | Loop length |
| `--fps` | 30 | Frame rate |
| `--size` | 1.0 | Droplet size multiplier |
| `--drops` | 80 | Number of sliding droplets (35 % are "large") |
| `--seed` | 7 | Random seed (positions, speeds, paths) |
| `--crf` | 18 | x264 quality (lower = better / larger) |

Rendering takes under a minute on a 16-thread CPU (frames are rendered in
parallel and piped to `ffmpeg`).

### How it works

1. **Mist** - a tileable noise field is rolled horizontally by exactly one image
   width per loop and modulates brightness by about +/-4.5 %.
2. **Glass breathing** - a coarse sinusoidal displacement map (integer temporal
   harmonics, hence periodic) gently warps the image by a few pixels.
3. **Droplets** - each droplet follows a stop-and-go path (a monotonic
   `u + a*sin(...)` easing) and is drawn as an elliptical lens: inverted,
   minified refraction of the frame behind it, dark rim, bottom caustic and a
   specular highlight, plus a short blurred/brightened trail. Opacity is zero at
   the start and end of each cycle, so the wrap-around is invisible.
4. A fixed film-grain pattern is added to avoid gradient banding after H.264
   compression.

The script has no dependency on the theme: point it at any similar blurred
wallpaper.
