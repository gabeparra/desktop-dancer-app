# Changelog

## 0.5.1 (2026-09-29)

- **Change clip…** in the tray menu. A clip you pick, or pass on the command line, is remembered for the next launch, the lunch screen and the screensaver.
- Works without the example clip too: it asks for a file, and prints usage if you cancel. Lunch mode and the screensaver never pop a dialog; with no clip they show just the sign.
- `--clip` is gone; pass a file path instead.

## 0.5.0 (2026-09-29)

- New bundled dancer: a Pexels clip by cottonbro studio (`--clip pajamas`, the default). It replaces the three earlier demo clips, which were copyrighted footage and are gone from the repo and its history. Any other clip is a file path away.
- The repo moved to the gabeparra account (now `gabeparra/desktop-dancer-app`).
- Shorter README with a banner and a demo GIF.

## 0.4.1 (2026-05-18)

- Window title no longer disappears on Windows.
- Right-click opens the menu instead of closing the dancer.
- Clip re-rendered with raw alpha so frames never drop out.

## 0.4.0 (2026-05-18)

- Lunch mode gets a 1-hour countdown timer by default.

## 0.3.0 (2026-05-18)

- Windows screensaver: CI builds `desktop-dancer.scr` next to the exe.

## 0.2.0 (2026-05-18)

- Full-screen "I'M ON LUNCH" overlay (`--lunch`, or from the tray menu).

## 0.1.0 (2026-05-06)

- First release: floating transparent dancer, tray icon, alpha-level controls for the matting, and a one-file Windows exe built by GitHub Actions.
