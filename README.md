<div align="center">
  <img src="assets/banner.png" alt="desktop-dancer" width="100%" />

  <br/>

  <a href="https://github.com/gabeparra/desktop-dancer/releases/latest"><img src="https://img.shields.io/github/v/release/gabeparra/desktop-dancer?color=3ddc97" alt="release" /></a>
  <img src="https://img.shields.io/badge/Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-2b1152" alt="platforms" />
  <img src="https://img.shields.io/badge/PyQt6-41CD52?logo=qt&logoColor=white" alt="PyQt6" />
  <img src="https://img.shields.io/badge/license-MIT-ff6fb1" alt="MIT" />
</div>

A real dancer, background removed, looping on top of your windows. Step away and she turns into a full-screen "I'M ON LUNCH" sign.

<p align="center"><img src="assets/demo.gif" alt="desktop-dancer floating over an editor and a terminal" width="720" /></p>

## Quick start

**Windows:** grab `desktop-dancer.exe` from the [latest release](https://github.com/gabeparra/desktop-dancer/releases/latest) and double-click it.

**macOS / Linux:**

```bash
git clone https://github.com/gabeparra/desktop-dancer.git
cd desktop-dancer
pip install PyQt6
python desktop_dancer.py
```

It starts with the example dancer. Right-click, then **Change clip…** to use your own; it's remembered next time.
Drag to move, scroll to resize, middle-click for click-through. Going to lunch? `desktop-dancer --lunch "back at 1pm" --timer 1h`, or install `desktop-dancer.scr` from the release as your Windows screensaver.

## How it works

1. **Matting.** [Robust Video Matting](https://github.com/PeterL1n/RobustVideoMatting) predicts an alpha matte for every frame of your video (`rvm_to_webp.py`, on CUDA).
2. **Alpha levels.** A levels curve snaps the matte's unsure middle to solid, so the dancer never looks see-through, and keeps the soft edges on hair.
3. **Animated WebP.** Frames are stored with their alpha. VP9-alpha lost its alpha in common ffmpeg builds and APNG came out about 30x bigger, so WebP it is.
4. **The window.** PyQt6 plays it with `QMovie` in a frameless, translucent, always-on-top tool window. Click-through flips Qt's transparent-for-input flag, and the tray icon always gets you back.

## Bring your own dancer

Any animated WebP or GIF works: `python desktop_dancer.py my_dance.webp`.

To cut one from a video you shot or have the rights to (needs an NVIDIA GPU and ffmpeg):

```bash
pip install torch torchvision numpy
ffmpeg -i source.mp4 -vf scale=1280:720 -an -c:v ffv1 src.mkv
python rvm_to_webp.py src.mkv my_dance.webp 1280 720 25 0 15   # w h fps start seconds
```

Blurry edges? Add `--backbone resnet50`. See-through or blocky dancer? Tune `--alpha-low` / `--alpha-high`.

## Credits

The bundled dancer is "Woman Wearing Sleepwear Dancing" by [cottonbro studio](https://www.pexels.com/video/9499408/) on Pexels, used under the [Pexels License](https://www.pexels.com/license/). Code is [MIT](LICENSE). Changes are in the [changelog](CHANGELOG.md).
