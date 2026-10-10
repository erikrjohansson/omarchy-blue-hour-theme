#!/usr/bin/env python3
"""Rain-on-glass live wallpaper: renders a seamless looping "rain on glass" video from the
theme's static wallpaper (drifting mist + sliding raindrops with lens refraction).

Usage: python rain.py <wallpaper.png> <out.mp4> [--seconds 24] [--fps 30] [--size 1.0] [--drops 80] [--seed 7]
       python rain.py <wallpaper.png> <frame.png> --frame <t_seconds>   (preview a single frame)
"""
import argparse, subprocess, sys
from multiprocessing import Pool
import cv2
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("out")
ap.add_argument("--seconds", type=float, default=24)
ap.add_argument("--fps", type=int, default=30)
ap.add_argument("--frame", type=float, default=None)
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--crf", type=int, default=18)
ap.add_argument("--size", type=float, default=1.0, help="drop size multiplier")
ap.add_argument("--drops", type=int, default=80)
args = ap.parse_args()

BASE = cv2.imread(args.src, cv2.IMREAD_COLOR)
H, W = BASE.shape[:2]
T = args.seconds
TAU = 2 * np.pi
rng = np.random.default_rng(args.seed)

# ---- tileable mist (drifts horizontally one full width per loop) ------------
def tile_noise(h, w, sigma):
    n = rng.random((h, w)).astype(np.float32)
    w = n.shape[1]
    n = cv2.GaussianBlur(np.tile(n, (1, 3)), (0, 0), sigma, borderType=cv2.BORDER_REFLECT)[:, w:2 * w]  # tileable in x
    n -= n.min(); n /= n.max()
    return n * 2 - 1

MIST_H, MIST_W = H // 4, W // 4
MIST = tile_noise(MIST_H, MIST_W, 28) * 0.7 + tile_noise(MIST_H, MIST_W, 60) * 0.3
MIST = cv2.resize(MIST, (W, H), interpolation=cv2.INTER_CUBIC)

GRAIN = rng.normal(0, 1.0, (H, W, 1)).astype(np.float32)  # fixed grain, kills banding

# coarse grid for the slow "breathing" warp of the glass
GH, GW = H // 16, W // 16
gy, gx = np.mgrid[0:GH, 0:GW].astype(np.float32)
gx *= 16; gy *= 16
MAPX0, MAPY0 = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))

# ---- drops -----------------------------------------------------------------
def make_drops():
    drops = []
    for i in range(args.drops):
        big = i < args.drops * 0.35
        r = rng.uniform(7, 16) if big else rng.uniform(3.5, 7)
        drops.append(dict(
            x=rng.uniform(0, W), y=rng.uniform(-50, H * 0.95),
            r=r * W / 2560 * args.size,
            D=rng.uniform(260, 800) if big else rng.uniform(90, 300),
            k=int(rng.choice([1, 1, 2])) if big else int(rng.choice([1, 2, 2, 3])),
            ph=rng.random(), n=int(rng.integers(2, 5)),
            a=rng.uniform(0.55, 0.9), wob=rng.uniform(0.5, 2.5), wm=int(rng.integers(1, 4)),
            wp=rng.random() * TAU,
        ))
    return drops

DROPS = make_drops()

def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)

def draw_drop(img, cx, cy, rx, alpha):
    ry = rx * 1.4
    pad = int(rx * 2.2) + 2
    x0, x1 = int(cx - pad), int(cx + pad)
    y0, y1 = int(cy - pad * 1.5), int(cy + pad * 1.5)
    x0c, y0c, x1c, y1c = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
    if x1c - x0c < 4 or y1c - y0c < 4:
        return
    roi = img[y0c:y1c, x0c:x1c]
    yy, xx = np.mgrid[y0c:y1c, x0c:x1c].astype(np.float32)
    nx, ny = (xx - cx) / rx, (yy - cy) / ry
    d2 = nx * nx + ny * ny
    inside = d2 < 1.0
    if not inside.any():
        return
    # refraction: the drop shows the scene upside down and minified
    g = 1.35
    mapx = (xx - nx * rx * g - x0c).astype(np.float32)
    mapy = (yy - ny * ry * g * 1.15 - y0c).astype(np.float32)
    mapx = np.where(inside, mapx, xx - x0c); mapy = np.where(inside, mapy, yy - y0c)
    refr = cv2.remap(roi.copy(), mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    z = np.sqrt(np.clip(1 - d2, 0, 1))
    d = np.sqrt(d2)
    shade = 1.0 - 0.28 * smooth(0.62, 1.0, d)                      # dark rim
    shade += 0.20 * np.exp(-(((nx - 0.05) / 0.55) ** 2 + ((ny - 0.62) / 0.28) ** 2))   # bottom caustic
    refr *= shade[..., None] * 1.04
    spec = np.exp(-(((nx + 0.38) / 0.20) ** 2 + ((ny + 0.45) / 0.17) ** 2))               # highlight
    refr += (spec * 150)[..., None]
    edge = (1 - smooth(0.90, 1.0, d)) * alpha
    out = roi.astype(np.float32) * (1 - edge[..., None]) + refr * edge[..., None]
    # soft drop shadow just below/right so it reads as a bead on the glass
    rim = smooth(0.95, 1.12, d) * (1 - smooth(1.12, 1.5, d)) * 0.10 * alpha
    out *= (1 - rim[..., None])
    roi[:] = np.clip(out, 0, 255).astype(np.uint8)

def draw_trail(img, cx, cy, rx, length, alpha):
    if length < 3:
        return
    y1 = int(min(cy, H)); y0 = int(max(cy - length, 0))
    if y1 - y0 < 2:
        return
    sig = max(rx * 0.38, 1.2)
    x0, x1 = int(max(cx - sig * 4, 0)), int(min(cx + sig * 4, W))
    if x1 - x0 < 2:
        return
    ys = np.arange(y0, y1, dtype=np.float32)
    xs = np.arange(x0, x1, dtype=np.float32)
    fade = ((ys - (cy - length)) / length).clip(0, 1) ** 1.5       # strong near the drop, gone at the tail
    prof = np.exp(-(((xs - cx) / sig) ** 2))
    m = (fade[:, None] * prof[None, :]) * alpha
    roi = img[y0:y1, x0:x1].astype(np.float32)
    blur = cv2.GaussianBlur(roi, (0, 0), 2.5)
    out = roi * (1 - 0.35 * m[..., None]) + blur * (0.35 * m[..., None]) + (m * 9)[..., None]
    img[y0:y1, x0:x1] = np.clip(out, 0, 255).astype(np.uint8)

def render(t):
    u0 = (t / T) % 1.0
    # 1) slow warp of the glass (periodic in T) + drifting mist
    s = lambda k, ph: np.sin(TAU * (k * u0) + ph)
    dx = (2.6 * np.sin(TAU * gx / 780 + TAU * u0 + 0.5) + 1.8 * np.sin(TAU * gy / 520 - 2 * TAU * u0 + 2.0)).astype(np.float32)
    dy = (2.2 * np.sin(TAU * gy / 640 + TAU * u0 + 1.1) + 1.5 * np.sin(TAU * gx / 430 + 3 * TAU * u0)).astype(np.float32)
    dxf = cv2.resize(dx, (W, H), interpolation=cv2.INTER_CUBIC)
    dyf = cv2.resize(dy, (W, H), interpolation=cv2.INTER_CUBIC)
    warped = cv2.remap(BASE, MAPX0 + dxf, MAPY0 + dyf, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    mist = np.roll(MIST, int(round(W * u0)), axis=1)
    f = warped.astype(np.float32) * (1 + 0.045 * mist[..., None]) + mist[..., None] * 3.0
    img = np.clip(f + GRAIN, 0, 255).astype(np.uint8)
    # 2) sliding drops
    for dr in DROPS:
        u = (u0 * dr["k"] + dr["ph"]) % 1.0
        p = u + dr["a"] * np.sin(TAU * dr["n"] * u) / (TAU * dr["n"])   # stop-and-go, monotonic
        alpha = float(smooth(0.0, 0.10, u) * (1 - smooth(0.82, 1.0, u)))
        if alpha <= 0.002:
            continue
        cy = dr["y"] + p * dr["D"]
        cx = dr["x"] + dr["wob"] * np.sin(TAU * dr["wm"] * u + dr["wp"])
        rx = dr["r"] * (0.9 + 0.2 * u)
        draw_trail(img, cx, cy - rx * 0.6, rx, min(p * dr["D"], 240) * alpha, alpha)
        draw_drop(img, cx, cy, rx, alpha)
    return img

def work(i):
    return render(i / args.fps).tobytes()

if __name__ == "__main__":
    if args.frame is not None:
        cv2.imwrite(args.out, render(args.frame)); sys.exit()
    n = int(round(T * args.fps))
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
         "-r", str(args.fps), "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", str(args.crf),
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", args.out],
        stdin=subprocess.PIPE)
    with Pool(12) as pool:
        for k, fr in enumerate(pool.imap(work, range(n), chunksize=2)):
            ff.stdin.write(fr)
            if k % 60 == 0:
                print(f"{k}/{n}", flush=True)
    ff.stdin.close(); ff.wait()
    print("done", args.out)
