"""Frameless transparent always-on-top dancer + fullscreen 'on lunch' mode.

Three modes:

Normal (default): a small floating dancer window with a tray icon.

    desktop-dancer                          # your last clip, else the example dancer
    desktop-dancer my_dance.webp            # any animated WebP or GIF

One example dancer ships with the app. A clip you open is remembered for next
time, and the tray menu has "Change clip..." to swap it.

Lunch: fullscreen "I'M ON LUNCH" away screen with the dancer in the middle.

    desktop-dancer --lunch "back at 1pm"
    desktop-dancer --lunch "lunch, back ~1pm" my_dance.webp
    desktop-dancer --lunch "brb" --title "AFK" --timer 30m
    desktop-dancer --lunch --timer 0        # hide the default 1h countdown

The tray icon also has a "Go on lunch..." menu entry that pops a prompt for the
message, timer, and title so you don't have to relaunch from the command line.

Screensaver: rename/copy the built exe to ``desktop-dancer.scr`` and Windows will
treat it as a screen saver. The OS passes ``/s`` (fullscreen), ``/c`` (settings),
or ``/p:HWND`` (preview rectangle); we handle all three. In ``/s`` mode the
overlay exits on any mouse motion, click, or keypress. It plays your last clip
(or the example), and shows just the lunch sign if there's neither.

Window controls (when not click-through):
    Drag           move
    Scroll         resize
    Right-click    open the menu at the cursor
    Middle-click   toggle click-through (when a system tray is available)
    Drop file      swap to a dropped animated WebP or GIF
    Space          pause / resume
    Ctrl+Q         quit

Lunch overlay:
    Esc            dismiss
"""
import argparse
import re
import sys
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QSize, QPoint, QRect, QTimer, QTime, QDateTime, QSettings, QObject,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QMovie, QIcon, QPixmap, QPainter, QAction, QActionGroup, QFont,
    QImageReader, QCursor, QGuiApplication, QKeySequence,
)
from PyQt6.QtWidgets import (
    QApplication, QLabel, QWidget, QSystemTrayIcon, QMenu,
    QVBoxLayout, QFormLayout, QDialog, QDialogButtonBox, QLineEdit,
    QMessageBox, QFileDialog,
)

__version__ = "0.5.2"

CLIP_FILTER = "Animated clips (*.webp *.gif);;All files (*)"
EXAMPLE_CLIP = "pajama_dance.webp"  # bundled when present; builds work without it
DEFAULT_LUNCH_TITLE = "I'M ON LUNCH"
DEFAULT_LUNCH_TIMER_SECONDS = 3600
RESIZE_PRESETS = [("25%", 0.25), ("50%", 0.5), ("75%", 0.75), ("100%", 1.0), ("150%", 1.5)]


def settings() -> QSettings:
    return QSettings("desktop-dancer", "desktop-dancer")


def playable(path: Path) -> bool:
    """True if ``path`` is an existing animated image Qt's QMovie can play."""
    if not path.is_file():
        return False
    reader = QImageReader(str(path))
    if not reader.canRead() or not reader.supportsAnimation():
        return False
    return QMovie(str(path)).isValid()


def remembered_clip() -> Path | None:
    """The last clip that played, if it's still on disk and still readable."""
    value = settings().value("clip", "", type=str)
    return Path(value) if value and playable(Path(value)) else None


def example_clip() -> Path | None:
    """The bundled example (PyInstaller _MEIPASS or next to this file), if any."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    path = base / EXAMPLE_CLIP
    return path if path.is_file() else None


def remember_clip(path: Path) -> None:
    settings().setValue("clip", str(path))


def forget_clip() -> None:
    settings().remove("clip")


def _report_error(message: str) -> None:
    """Show a user-facing error whether or not a console stderr is attached."""
    if sys.stderr is not None:
        print(f"desktop-dancer: {message}", file=sys.stderr)
        return
    if QApplication.instance() is not None:
        QMessageBox.critical(None, "desktop-dancer", message)


def pick_clip() -> Path | None:
    """File picker that only returns something QMovie can actually play."""
    start = str((remembered_clip() or Path.home() / "x").parent)
    while True:
        name, _ = QFileDialog.getOpenFileName(None, "Pick a dance clip", start, CLIP_FILTER)
        if not name:
            return None
        path = Path(name)
        if playable(path):
            return path
        QMessageBox.warning(
            None, "desktop-dancer",
            f"Can't play {path.name}. Pick an animated WebP or GIF.",
        )


def resolve_clip(explicit_path: str | None, ask: bool = True) -> Path | None:
    """A path on the command line wins, then your last clip, then the bundled
    example, then (if ``ask``) a file picker. Clips you choose are remembered;
    the example never is, since it lives in a temp dir inside the exe.
    None means there's nothing to play."""
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if not playable(path):
            _report_error(f"Can't play {path}. Pass an animated WebP or GIF.")
            sys.exit(1)
        remember_clip(path)
        return path
    found = remembered_clip() or example_clip()
    if found is not None or not ask:
        return found
    path = pick_clip()
    if path is not None:
        remember_clip(path)
    return path


_DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


def parse_duration(text: str) -> int:
    """Parse '1h', '30m', '1h30m', '1h 30m', '90s', '0', 'off', or seconds."""
    s = re.sub(r"\s+", "", text.strip().lower())
    if s in ("off", "none"):
        return 0
    if s.isdigit():
        return int(s)
    m = _DURATION_RE.match(s)
    if not m or not any(m.groups()):
        raise argparse.ArgumentTypeError(
            f"can't parse duration {text!r}; try '1h', '30m', '1h30m', '90s', or '0'"
        )
    h, mn, sec = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mn * 60 + sec


def clip_native_size(path: Path, movie: QMovie | None = None) -> QSize:
    """Read a clip's native pixel dimensions without decoding all frames."""
    size = QImageReader(str(path)).size()
    if size.isValid() and not size.isEmpty():
        return size
    if movie is not None:
        size = movie.currentImage().size()
        if size.isEmpty():
            movie.jumpToNextFrame()
            size = movie.currentImage().size()
        if size.isValid() and not size.isEmpty():
            return size
    return QSize(640, 360)


def load_movie(path: Path) -> QMovie:
    m = QMovie(str(path))
    if not m.isValid():
        formats = [bytes(f).decode() for f in QImageReader.supportedImageFormats()]
        raise ValueError(f"QMovie can't read {path}. Supported: {formats}")
    # Stream frames instead of caching every decoded RGBA bitmap in memory.
    # For a 563-frame 1080x720 WebP, CacheAll eats 450 MB-3.9 GB of RAM while
    # CacheNone stays near ~6 MB and decodes in under 2 ms/frame.
    m.setCacheMode(QMovie.CacheMode.CacheNone)
    return m


def make_tray_icon() -> QIcon:
    """Build a tiny dancer-shaped icon procedurally so we don't ship a .ico."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(Qt.GlobalColor.magenta)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(22, 6, 20, 20)
    p.drawRoundedRect(20, 26, 24, 26, 6, 6)
    p.drawRoundedRect(22, 50, 8, 12, 3, 3)
    p.drawRoundedRect(34, 50, 8, 12, 3, 3)
    p.end()
    return QIcon(pm)


def clamp_point_to_screens(pos: QPoint, size: QSize) -> QPoint:
    """Keep a restored window visible if a monitor layout changed."""
    screens = QGuiApplication.screens()
    if not screens:
        return pos
    rect = QRect(pos, size)
    for screen in screens:
        avail = screen.availableGeometry()
        inter = rect.intersected(avail)
        if inter.width() >= min(48, size.width()) and inter.height() >= min(48, size.height()):
            return pos
    primary = QGuiApplication.primaryScreen() or screens[0]
    avail = primary.availableGeometry()
    max_x = max(avail.left(), avail.right() - size.width() + 1)
    max_y = max(avail.top(), avail.bottom() - size.height() + 1)
    x = max(avail.left(), min(pos.x(), max_x))
    y = max(avail.top(), min(pos.y(), max_y))
    return QPoint(x, y)


def default_dancer_pos(size: QSize, margin: int = 24) -> QPoint:
    """Place the dancer near the bottom-right corner on first launch."""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return QPoint(margin, margin)
    avail = screen.availableGeometry()
    x = max(avail.left(), avail.right() - size.width() - margin + 1)
    y = max(avail.top(), avail.bottom() - size.height() - margin + 1)
    return QPoint(x, y)


class Dancer(QWidget):
    click_through_changed = pyqtSignal(bool)
    paused_changed = pyqtSignal(bool)
    always_on_top_changed = pyqtSignal(bool)
    scale_changed = pyqtSignal(float)
    clip_changed = pyqtSignal(Path)

    def __init__(self, path: Path, allow_click_through: bool = True):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAcceptDrops(True)

        self.label = QLabel(self)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.label.setStyleSheet("background: transparent;")
        self.label.setScaledContents(True)

        self.movie: QMovie | None = None
        self.clip_path: Path = path
        self.base_size = QSize(640, 360)
        self._scale = self._load_saved_scale()
        self._paused = False
        self._always_on_top = True
        self._allow_click_through = allow_click_through
        self._drag_offset: QPoint | None = None
        self._click_through = False
        self._context_menu: QMenu | None = None

        self.set_clip(path)
        self._restore_position()

    def _load_saved_scale(self) -> float:
        raw = settings().value("scale", None)
        if raw is None:
            return 0.5
        try:
            return max(0.1, min(3.0, float(raw)))
        except (TypeError, ValueError):
            return 0.5

    def _restore_position(self) -> None:
        st = settings()
        x = st.value("pos_x", None)
        y = st.value("pos_y", None)
        if x is not None and y is not None:
            try:
                pos = clamp_point_to_screens(QPoint(int(x), int(y)), self.size())
                self.move(pos)
                return
            except (TypeError, ValueError):
                pass
        self.move(default_dancer_pos(self.size()))

    def save_state(self) -> None:
        st = settings()
        st.setValue("scale", round(self._scale, 4))
        st.setValue("pos_x", self.x())
        st.setValue("pos_y", self.y())

    def set_clip(self, path: Path):
        """Swap the playing clip, keeping the current scale."""
        new_movie = load_movie(path)
        new_base = clip_native_size(path, new_movie)

        old_movie = self.movie
        if old_movie is not None:
            old_movie.stop()
            old_movie.deleteLater()

        self.clip_path = path
        self.base_size = new_base
        self.movie = new_movie
        self.movie.setParent(self)
        self.movie.finished.connect(self._on_movie_finished)
        self.label.setMovie(self.movie)
        self._apply_scale()
        self.movie.start()
        if self._paused:
            self.movie.setPaused(True)
        self.clip_changed.emit(path)

    def _on_movie_finished(self):
        # Ensure clips exported without an infinite loop count keep dancing.
        if self.movie is not None and not self._paused:
            self.movie.start()

    def set_context_menu(self, menu: QMenu):
        """Hand the dancer the tray's menu so right-click can pop it."""
        self._context_menu = menu

    def _apply_scale(self):
        bw = max(1, self.base_size.width())
        bh = max(1, self.base_size.height())
        # Keep the dancer visible while strictly preserving aspect ratio.
        min_scale = max(64.0 / max(bw, bh), 0.1)
        eff_scale = max(min_scale, self._scale)
        w = max(1, round(bw * eff_scale))
        h = max(1, round(bh * eff_scale))
        if self.movie is not None:
            self.movie.setScaledSize(QSize(w, h))
        self.label.resize(w, h)
        self.resize(w, h)

    def set_scale(self, scale: float):
        clamped = max(0.1, min(3.0, scale))
        if clamped == self._scale and self.size() == self.label.size():
            return
        self._scale = clamped
        self._apply_scale()
        settings().setValue("scale", round(self._scale, 4))
        self.scale_changed.emit(self._scale)

    def set_paused(self, paused: bool):
        if paused == self._paused:
            return
        self._paused = paused
        if self.movie is not None:
            self.movie.setPaused(paused)
        self.paused_changed.emit(paused)

    def toggle_paused(self):
        self.set_paused(not self._paused)

    def _apply_window_flags(self, flags: Qt.WindowType):
        was_visible = self.isVisible()
        pos = self.pos()
        self.setWindowFlags(flags)
        self.move(pos)
        if was_visible:
            self.show()

    def set_always_on_top(self, on: bool):
        if on == self._always_on_top:
            return
        self._always_on_top = on
        flags = self.windowFlags()
        if on:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self._apply_window_flags(flags)
        self.always_on_top_changed.emit(on)

    def set_click_through(self, on: bool):
        if on and not self._allow_click_through:
            self.click_through_changed.emit(False)
            return
        if on == self._click_through:
            return
        self._click_through = on
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, on)
        flags = self.windowFlags()
        if on:
            flags |= Qt.WindowType.WindowTransparentForInput
        else:
            flags &= ~Qt.WindowType.WindowTransparentForInput
        self._apply_window_flags(flags)
        self.click_through_changed.emit(on)

    def toggle_click_through(self):
        self.set_click_through(not self._click_through)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # Wayland forbids client-driven window.move(), so hand off to the
            # compositor there and keep manual dragging elsewhere.
            handle = self.windowHandle()
            if (
                QGuiApplication.platformName().startswith("wayland")
                and handle is not None
                and handle.startSystemMove()
            ):
                self._drag_offset = None
                return
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif e.button() == Qt.MouseButton.RightButton:
            # Show the shared menu at the cursor so every action stays discoverable.
            if self._context_menu is not None:
                self._context_menu.popup(e.globalPosition().toPoint())
        elif e.button() == Qt.MouseButton.MiddleButton:
            self.toggle_click_through()

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e):
        if self._drag_offset is not None:
            self._drag_offset = None
            self.save_state()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120
        if steps:
            self.set_scale(self._scale * (1.1 ** steps))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space:
            self.toggle_paused()
        elif e.matches(QKeySequence.StandardKey.Quit):
            QApplication.quit()
        else:
            super().keyPressEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for url in e.mimeData().urls():
                if url.isLocalFile() and playable(Path(url.toLocalFile())):
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if playable(path):
                try:
                    self.set_clip(path)
                except ValueError as err:
                    QMessageBox.warning(self, "desktop-dancer", str(err))
                    return
                remember_clip(path)
                e.acceptProposedAction()
                return
        e.ignore()

    def closeEvent(self, e):
        self.save_state()
        if self.movie is not None:
            self.movie.stop()
        super().closeEvent(e)


class _ScreenBackdrop(QWidget):
    """Solid dark backdrop for secondary monitors in screensaver mode."""

    def __init__(self, on_trigger):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet("background-color: rgb(11, 10, 22);")
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self._on_trigger = on_trigger
        self._armed = False
        self._start_mouse_pos: QPoint | None = None

    def showEvent(self, e):
        super().showEvent(e)
        self._start_mouse_pos = QCursor.pos()
        QTimer.singleShot(350, self._arm)

    def _arm(self):
        self._armed = True
        self._start_mouse_pos = QCursor.pos()

    def keyPressEvent(self, e):
        self._on_trigger()

    def mousePressEvent(self, e):
        self._on_trigger()

    def mouseMoveEvent(self, e):
        if not self._armed or self._start_mouse_pos is None:
            return
        d = QCursor.pos() - self._start_mouse_pos
        if abs(d.x()) + abs(d.y()) > 5:
            self._on_trigger()


class LunchOverlay(QWidget):
    """Fullscreen "I'M ON LUNCH" away screen with a dancer animating in the middle.

    Esc dismisses. If ``on_dismiss`` is set, it is called instead of quitting the app,
    used so the tray-launched overlay returns to the dancer rather than ending the
    process.
    """

    def __init__(
        self, clip_path: Path | None, title: str, message: str,
        on_dismiss=None, screensaver: bool = False,
        timer_seconds: int | None = None,
    ):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet("background-color: rgb(11, 10, 22);")
        self._on_dismiss = on_dismiss
        self._screensaver = screensaver
        self._dismissed = False
        self._armed = not screensaver
        self._start_mouse_pos: QPoint | None = None
        self._backdrops: list[_ScreenBackdrop] = []
        self._movie_native_size = QSize(640, 360)

        if screensaver:
            self.setMouseTracking(True)
            self.setCursor(Qt.CursorShape.BlankCursor)

        # `background: transparent` is critical on Windows: without it QLabel
        # inherits the OS palette (light bg) and white-on-white renders invisible.
        self.title_label = QLabel(title.upper())
        self.title_label.setStyleSheet("color: white; background: transparent;")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)

        self.msg_label = QLabel(message)
        self.msg_label.setStyleSheet("color: #d4d2e0; background: transparent;")
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_label.setWordWrap(True)
        if not message:
            self.msg_label.hide()

        self._timer_end: QDateTime | None = None
        if timer_seconds and timer_seconds > 0:
            self._timer_end = QDateTime.currentDateTime().addSecs(timer_seconds)
        self.timer_label = QLabel("")
        self.timer_label.setStyleSheet("color: #d8a4ff; background: transparent;")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self._timer_end is None:
            self.timer_label.hide()
        else:
            self._tick_timer()

        self.clock = QLabel("")
        self.clock.setStyleSheet("color: #8c89a6; background: transparent;")
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tick_clock()
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick)
        self._clock_timer.start(1000)

        # Dancer loop, when there's a readable clip. Without one it's just the sign.
        self.dancer_label = QLabel()
        self.dancer_label.setStyleSheet("background: transparent;")
        self.dancer_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.dancer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dancer_label.setScaledContents(True)
        self.movie: QMovie | None = None
        if clip_path is not None:
            try:
                self.movie = load_movie(clip_path)
            except ValueError:
                self.movie = None
        if self.movie is not None and clip_path is not None:
            self.movie.setParent(self)
            self._movie_native_size = clip_native_size(clip_path, self.movie)
            self.movie.finished.connect(self._on_movie_finished)
            self.dancer_label.setMovie(self.movie)
        else:
            self.dancer_label.hide()

        hint_text = "move mouse or press any key to exit" if screensaver else "press Esc to dismiss"
        self.hint = QLabel(hint_text)
        self.hint.setStyleSheet("color: #66637d; background: transparent;")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(40, 28, 40, 28)
        self._layout.setSpacing(12)
        self._layout.addStretch(1)
        self._layout.addWidget(self.title_label)
        self._layout.addWidget(self.msg_label)
        self._layout.addWidget(self.timer_label)
        self._layout.addWidget(self.clock)
        self._layout.addSpacing(12)
        self._layout.addWidget(self.dancer_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self._layout.addStretch(2)
        self._layout.addWidget(self.hint)

        self._update_responsive_layout(QSize(1280, 720))
        if self.movie is not None:
            self.movie.start()

    def _on_movie_finished(self):
        if self.movie is not None:
            self.movie.start()

    def _update_responsive_layout(self, target_size: QSize):
        """Scale fonts and dancer height to fit cleanly on 720p through 4K screens."""
        w = max(320, target_size.width())
        h = max(240, target_size.height())

        margin_y = max(16, min(40, int(h * 0.035)))
        margin_x = max(24, min(64, int(w * 0.04)))
        spacing = max(6, min(16, int(h * 0.014)))
        self._layout.setContentsMargins(margin_x, margin_y, margin_x, margin_y)
        self._layout.setSpacing(spacing)

        font_family = "Segoe UI"
        title_pt = max(24, min(88, int(h * 0.068)))
        msg_pt = max(16, min(36, int(h * 0.028)))
        timer_pt = max(20, min(54, int(h * 0.042)))
        clock_pt = max(13, min(24, int(h * 0.019)))
        hint_pt = max(11, min(14, int(h * 0.013)))

        self.title_label.setFont(QFont(font_family, title_pt, QFont.Weight.Black))
        self.msg_label.setFont(QFont(font_family, msg_pt))
        self.timer_label.setFont(QFont(font_family, timer_pt, QFont.Weight.Bold))
        self.clock.setFont(QFont(font_family, clock_pt))
        self.hint.setFont(QFont(font_family, hint_pt))

        if self.movie is None:
            return

        # Reserve space for visible text labels + margins + spacing so the dancer
        # never pushes the bottom hint or itself off-screen.
        chrome_h = margin_y * 2 + spacing * 6 + 12
        for lbl in (self.title_label, self.msg_label, self.timer_label, self.clock, self.hint):
            if not lbl.isHidden():
                chrome_h += lbl.sizeHint().height()

        avail_h = max(80, h - chrome_h)
        target_h = min(int(h * 0.42), avail_h)
        max_w = max(120, int((w - margin_x * 2) * 0.9))

        nw = max(1, self._movie_native_size.width())
        nh = max(1, self._movie_native_size.height())
        scale = min(target_h / nh, max_w / nw)
        scaled_w = max(1, round(nw * scale))
        scaled_h = max(1, round(nh * scale))

        self.movie.setScaledSize(QSize(scaled_w, scaled_h))
        self.dancer_label.setFixedSize(scaled_w, scaled_h)

    def _tick_clock(self):
        self.clock.setText(QTime.currentTime().toString("h:mm AP"))

    def _tick_timer(self):
        if self._timer_end is None:
            return
        remaining = max(0, QDateTime.currentDateTime().secsTo(self._timer_end))
        if remaining <= 0:
            self.timer_label.setStyleSheet("color: #3ddc97; background: transparent;")
            self.timer_label.setText("back any minute now")
            return
        h, r = divmod(remaining, 3600)
        m, s = divmod(r, 60)
        self.timer_label.setText(
            f"back in {h}:{m:02d}:{s:02d}" if h else f"back in {m:02d}:{s:02d}"
        )

    def _tick(self):
        self._tick_clock()
        self._tick_timer()

    def _show_secondary_backdrops(self):
        if not self._screensaver or self._backdrops:
            return
        my_screen = self.screen() or QGuiApplication.primaryScreen()
        for scr in QGuiApplication.screens():
            if scr is my_screen:
                continue
            bd = _ScreenBackdrop(self._dismiss)
            bd.setGeometry(scr.geometry())
            bd.showFullScreen()
            self._backdrops.append(bd)

    def _close_backdrops(self):
        for bd in self._backdrops:
            bd.close()
        self._backdrops.clear()

    def _arm_screensaver(self):
        self._armed = True
        self._start_mouse_pos = QCursor.pos()

    def _dismiss(self):
        if self._dismissed:
            return
        self._dismissed = True
        self._close_backdrops()
        self.close()
        if self._on_dismiss:
            self._on_dismiss()
        else:
            QApplication.quit()

    def showEvent(self, e):
        super().showEvent(e)
        if self._screensaver:
            self._armed = False
            self._start_mouse_pos = QCursor.pos()
            QTimer.singleShot(350, self._arm_screensaver)
            self._show_secondary_backdrops()
        target = self.size()
        if self.isFullScreen() and self.screen() is not None:
            target = self.screen().geometry().size()
        self._update_responsive_layout(target)
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_responsive_layout(e.size())

    def closeEvent(self, e):
        self._clock_timer.stop()
        if self.movie is not None:
            self.movie.stop()
        self._close_backdrops()
        super().closeEvent(e)

    # Screensaver convention: any key, click, or non-trivial mouse motion ends it.
    # In lunch mode it stays Esc-only so a stray bump doesn't wipe the away screen.
    def keyPressEvent(self, e):
        if self._screensaver or e.key() == Qt.Key.Key_Escape:
            self._dismiss()

    def mousePressEvent(self, e):
        if self._screensaver:
            self._dismiss()

    def mouseMoveEvent(self, e):
        if not self._screensaver or not self._armed or self._start_mouse_pos is None:
            return
        d = QCursor.pos() - self._start_mouse_pos
        if abs(d.x()) + abs(d.y()) > 5:  # standard ~5px jitter tolerance
            self._dismiss()


class LunchDialog(QDialog):
    """Compact prompt for launching lunch mode from the tray or context menu."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Go on lunch")
        self.setMinimumWidth(340)

        self.message_edit = QLineEdit()
        self.message_edit.setPlaceholderText("Optional (e.g. back at 1pm)")

        self.timer_edit = QLineEdit("1h")
        self.timer_edit.setPlaceholderText("1h, 30m, 1h30m, or 0 to hide")

        self.title_edit = QLineEdit(DEFAULT_LUNCH_TITLE)

        form = QFormLayout()
        form.addRow("Message:", self.message_edit)
        form.addRow("Timer:", self.timer_edit)
        form.addRow("Title:", self.title_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.timer_seconds: int = DEFAULT_LUNCH_TIMER_SECONDS
        self.message_edit.setFocus()

    def _validate_and_accept(self):
        raw_timer = self.timer_edit.text().strip()
        if not raw_timer:
            self.timer_seconds = 0
            self.accept()
            return
        try:
            self.timer_seconds = parse_duration(raw_timer)
        except argparse.ArgumentTypeError as err:
            QMessageBox.warning(self, "Invalid timer", str(err))
            self.timer_edit.selectAll()
            self.timer_edit.setFocus()
            return
        self.accept()

    def values(self) -> tuple[str, str, int]:
        title = self.title_edit.text().strip() or DEFAULT_LUNCH_TITLE
        message = self.message_edit.text().strip()
        return title, message, self.timer_seconds


class TrayController(QObject):
    def __init__(self, app: QApplication, dancer: Dancer):
        super().__init__(app)
        self.app = app
        self.dancer = dancer
        self._overlay: LunchOverlay | None = None
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray = QSystemTrayIcon(make_tray_icon(), parent=app)
        self.tray.setToolTip("desktop-dancer")

        self.menu = QMenu()

        lunch_action = QAction("Go on lunch…", self.menu)
        lunch_action.triggered.connect(self._enter_lunch_mode)
        self.menu.addAction(lunch_action)

        clip_action = QAction("Change clip…", self.menu)
        clip_action.triggered.connect(self._change_clip)
        self.menu.addAction(clip_action)

        self.example_action = QAction("Use example dancer", self.menu)
        self.example_action.triggered.connect(self._use_example_clip)
        self.menu.addAction(self.example_action)
        self.menu.addSeparator()

        self.pause_action = QAction("Pause", self.menu, checkable=True)
        self.pause_action.toggled.connect(self.dancer.set_paused)
        self.dancer.paused_changed.connect(self._sync_paused)
        self.menu.addAction(self.pause_action)

        self.top_action = QAction("Always on top", self.menu, checkable=True)
        self.top_action.setChecked(True)
        self.top_action.toggled.connect(self.dancer.set_always_on_top)
        self.dancer.always_on_top_changed.connect(self._sync_always_on_top)
        self.menu.addAction(self.top_action)

        move_action = QAction("Move (briefly enables clicks)", self.menu)
        move_action.triggered.connect(self._enter_move_mode)
        self.menu.addAction(move_action)

        self.ct_action = QAction("Click-through", self.menu, checkable=True)
        self.ct_action.setEnabled(self._tray_available)
        if not self._tray_available:
            self.ct_action.setToolTip("Click-through requires a system tray icon so you can turn it off.")
        self.ct_action.toggled.connect(self.dancer.set_click_through)
        self.dancer.click_through_changed.connect(self._sync_click_through)
        self.menu.addAction(self.ct_action)

        resize_menu = self.menu.addMenu("Resize")
        self._resize_group = QActionGroup(resize_menu)
        self._resize_group.setExclusive(True)
        self._resize_actions: list[tuple[float, QAction]] = []
        for label, scale in RESIZE_PRESETS:
            a = QAction(label, resize_menu, checkable=True)
            a.triggered.connect(lambda _, s=scale: self.dancer.set_scale(s))
            self._resize_group.addAction(a)
            resize_menu.addAction(a)
            self._resize_actions.append((scale, a))
        self.dancer.scale_changed.connect(self._sync_scale)
        self._sync_scale(self.dancer._scale)

        self.dancer.clip_changed.connect(self._sync_example_action)
        self._sync_example_action(self.dancer.clip_path)

        self.menu.addSeparator()
        quit_action = QAction("Quit", self.menu)
        quit_action.triggered.connect(self._quit)
        self.menu.addAction(quit_action)

        self.tray.setContextMenu(self.menu)
        self.dancer.set_context_menu(self.menu)  # share with the dancer's right-click
        self.tray.activated.connect(self._on_activate)
        if self._tray_available:
            self.tray.show()

    def _sync_click_through(self, on: bool):
        self.ct_action.blockSignals(True)
        self.ct_action.setChecked(on)
        self.ct_action.blockSignals(False)

    def _sync_paused(self, paused: bool):
        self.pause_action.blockSignals(True)
        self.pause_action.setChecked(paused)
        self.pause_action.blockSignals(False)

    def _sync_always_on_top(self, on: bool):
        self.top_action.blockSignals(True)
        self.top_action.setChecked(on)
        self.top_action.blockSignals(False)

    def _sync_scale(self, current: float):
        for scale, action in self._resize_actions:
            action.setChecked(abs(current - scale) < 0.02)

    def _sync_example_action(self, current_clip: Path):
        ex = example_clip()
        can_reset = ex is not None and ex.resolve() != current_clip.resolve()
        self.example_action.setVisible(ex is not None)
        self.example_action.setEnabled(can_reset)

    def _on_activate(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._enter_move_mode()

    def _enter_move_mode(self):
        if self.dancer._click_through:
            self.dancer.set_click_through(False)
        self.dancer.show()
        self.dancer.raise_()
        self.dancer.activateWindow()

    def _change_clip(self):
        path = pick_clip()
        if path is not None:
            try:
                self.dancer.set_clip(path)
            except ValueError as err:
                QMessageBox.warning(None, "desktop-dancer", str(err))
                return
            remember_clip(path)

    def _use_example_clip(self):
        ex = example_clip()
        if ex is None:
            return
        try:
            self.dancer.set_clip(ex)
        except ValueError as err:
            QMessageBox.warning(None, "desktop-dancer", str(err))
            return
        forget_clip()

    def _enter_lunch_mode(self):
        if self._overlay is not None:
            return
        dlg = LunchDialog()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        title, message, timer_seconds = dlg.values()
        # Temporarily prevent quitting while swapping Dancer -> LunchOverlay on
        # desktops that do not have a system tray.
        self.app.setQuitOnLastWindowClosed(False)
        self.dancer.hide()
        self._overlay = LunchOverlay(
            self.dancer.clip_path, title, message,
            on_dismiss=self._exit_lunch_mode,
            timer_seconds=timer_seconds,
        )
        self._overlay.showFullScreen()

    def _exit_lunch_mode(self):
        self._overlay = None
        self.dancer.show()
        self.app.setQuitOnLastWindowClosed(not self._tray_available)

    def _quit(self):
        self.dancer.save_state()
        self.app.quit()


def parse_screensaver_args(argv: list[str]) -> str | None:
    """Detect the Windows screensaver invocation style.

    Windows runs `.scr` files with one of:

    * ``/s``            start fullscreen, exit on input
    * ``/c`` / ``/c:N`` open the Settings dialog
    * ``/p:N`` / ``/p N`` render into preview HWND ``N`` (not embedded; exits cleanly)

    Accepts both forward-slash and dash variants for safety. Returns ``'s'``,
    ``'c'``, ``'p'`` or ``None``.
    """
    if len(argv) < 2:
        return None
    a = argv[1].lower()
    if a in ("/s", "-s"):
        return "s"
    if a == "/c" or a == "-c" or a.startswith("/c:") or a.startswith("-c:"):
        return "c"
    if a.startswith("/p") or a.startswith("-p"):
        return "p"
    return None


def run_screensaver(mode: str) -> int:
    """Handle a ``.scr`` invocation. Always returns an exit code."""
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(True)

    if mode == "s":
        clip = remembered_clip() or example_clip()  # never a dialog here
        overlay = LunchOverlay(
            clip, DEFAULT_LUNCH_TITLE, "",
            screensaver=True,
            timer_seconds=DEFAULT_LUNCH_TIMER_SECONDS,
        )
        overlay.showFullScreen()
        return app.exec()

    if mode == "c":
        clip = remembered_clip()
        if clip is not None:
            now_playing = f"Plays your last clip ({clip.name}) under an 'I'M ON LUNCH' sign."
        elif example_clip() is not None:
            now_playing = ("Plays the example dancer under an 'I'M ON LUNCH' sign. "
                           "Pick your own clip in desktop-dancer.exe to use that instead.")
        else:
            now_playing = ("No clip yet: open desktop-dancer.exe once and pick one. "
                           "Until then it shows just the 'I'M ON LUNCH' sign.")
        QMessageBox.information(
            None, "desktop-dancer screensaver",
            now_playing + "\n\n"
            "Move the mouse or press any key to exit while it's running.\n\n"
            "For a custom message, launch desktop-dancer.exe directly with "
            "`--lunch \"your message here\"`.",
        )
        return 0

    # mode == "p": Personalization preview rectangle. Exit cleanly so the
    # Personalization panel doesn't hang waiting for us.
    return 0


class _SafeArgumentParser(argparse.ArgumentParser):
    """Avoid crashing in Windows windowed builds where sys.stdout/stderr are None."""

    def _print_message(self, message, file=None):
        if message and file is not None:
            file.write(message)


def build_arg_parser() -> argparse.ArgumentParser:
    p = _SafeArgumentParser(
        prog="desktop-dancer",
        description="Floating transparent dancer / fullscreen 'on lunch' screen.",
    )
    p.add_argument(
        "path", nargs="?",
        help="Animated WebP or GIF to play. Without one: your last clip, "
             "else the example dancer, else a file picker.",
    )
    p.add_argument(
        "--lunch", metavar="MESSAGE", nargs="?", const="",
        help="Launch in fullscreen 'on lunch' mode showing this message. "
             "Pass alone (e.g. `--lunch`) to show just the 1h timer + clock.",
    )
    p.add_argument(
        "--title", default=DEFAULT_LUNCH_TITLE,
        help="Big header text for lunch mode (default: %(default)s).",
    )
    p.add_argument(
        "--timer", type=parse_duration, default=None, metavar="DURATION",
        help="Countdown timer for lunch mode (default: 1h; e.g. '30m', '1h30m', '90s', or '0' to hide).",
    )
    p.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    return p


def normalize_cli_args(args: argparse.Namespace) -> argparse.Namespace:
    """Resolve CLI conveniences like default lunch timer and `--lunch clip.webp`."""
    if args.lunch is not None:
        if args.path is None and args.lunch:
            candidate = Path(args.lunch).expanduser()
            if candidate.is_file() and candidate.suffix.lower() in (".webp", ".gif"):
                args.path = args.lunch
                args.lunch = ""
        if args.timer is None:
            args.timer = DEFAULT_LUNCH_TIMER_SECONDS
    return args


def main(argv: list[str] | None = None):
    raw_argv = sys.argv if argv is None else argv
    # Windows screensaver invocation (.scr /s, /c, /p:HWND) bypasses argparse
    # because the args start with `/`, which argparse doesn't recognize.
    ss = parse_screensaver_args(raw_argv)
    if ss is not None:
        sys.exit(run_screensaver(ss))

    args = normalize_cli_args(build_arg_parser().parse_args(raw_argv[1:]))

    app = QApplication(raw_argv[:1])
    tray_available = QSystemTrayIcon.isSystemTrayAvailable()
    app.setQuitOnLastWindowClosed(not tray_available)

    if args.lunch is not None:
        app.setQuitOnLastWindowClosed(True)
        # Heading out shouldn't start with a file dialog: no clip, just the sign.
        clip = resolve_clip(args.path, ask=False)
        overlay = LunchOverlay(
            clip, args.title, args.lunch, timer_seconds=args.timer,
        )
        overlay.showFullScreen()
        sys.exit(app.exec())

    clip = resolve_clip(args.path)
    if clip is None:
        if sys.stderr is not None:
            build_arg_parser().print_usage(sys.stderr)
            print("desktop-dancer: no clip picked. Try: desktop-dancer my_dance.webp",
                  file=sys.stderr)
        sys.exit(2)

    try:
        dancer = Dancer(clip, allow_click_through=tray_available)
    except ValueError as err:
        _report_error(str(err))
        sys.exit(1)

    dancer.show()
    tray_controller = TrayController(app, dancer)
    app.aboutToQuit.connect(dancer.save_state)
    _ = tray_controller
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
