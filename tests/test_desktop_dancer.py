"""Tests for desktop_dancer.py."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt, QPoint, QPointF, QSize, QSettings, QMimeData, QUrl
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QApplication, QDialog

import desktop_dancer as dd


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_WEBP = REPO_ROOT / "pajama_dance.webp"
DEMO_GIF = REPO_ROOT / "assets" / "demo.gif"
BANNER_PNG = REPO_ROOT / "assets" / "banner.png"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    ini = tmp_path / "settings.ini"

    def _make_settings():
        return QSettings(str(ini), QSettings.Format.IniFormat)

    monkeypatch.setattr(dd, "settings", _make_settings)
    return _make_settings


def test_parse_duration_variants():
    assert dd.parse_duration("1h") == 3600
    assert dd.parse_duration("30m") == 1800
    assert dd.parse_duration("1h30m") == 5400
    assert dd.parse_duration("1h 30m 15s") == 5415
    assert dd.parse_duration("90s") == 90
    assert dd.parse_duration("45") == 45
    assert dd.parse_duration("0") == 0
    assert dd.parse_duration("off") == 0
    assert dd.parse_duration("NONE") == 0
    with pytest.raises(dd.argparse.ArgumentTypeError):
        dd.parse_duration("")
    with pytest.raises(dd.argparse.ArgumentTypeError):
        dd.parse_duration("bogus")


def test_parse_screensaver_args():
    assert dd.parse_screensaver_args(["prog"]) is None
    assert dd.parse_screensaver_args(["prog", "/s"]) == "s"
    assert dd.parse_screensaver_args(["prog", "-S"]) == "s"
    assert dd.parse_screensaver_args(["prog", "/c"]) == "c"
    assert dd.parse_screensaver_args(["prog", "/c:12345"]) == "c"
    assert dd.parse_screensaver_args(["prog", "-c:99"]) == "c"
    assert dd.parse_screensaver_args(["prog", "/p:12345"]) == "p"
    assert dd.parse_screensaver_args(["prog", "/p", "12345"]) == "p"
    assert dd.parse_screensaver_args(["prog", "--lunch"]) is None


def test_cli_lunch_defaults_and_path_convenience():
    parser = dd.build_arg_parser()

    args = dd.normalize_cli_args(parser.parse_args(["--lunch"]))
    assert args.lunch == ""
    assert args.timer == 3600
    assert args.title == "I'M ON LUNCH"

    args = dd.normalize_cli_args(parser.parse_args(["--lunch", "back at 1pm", "--timer", "30m"]))
    assert args.lunch == "back at 1pm"
    assert args.timer == 1800

    args = dd.normalize_cli_args(parser.parse_args(["--lunch", "--timer", "0"]))
    assert args.lunch == ""
    assert args.timer == 0

    args = dd.normalize_cli_args(parser.parse_args(["--lunch", str(EXAMPLE_WEBP)]))
    assert args.lunch == ""
    assert args.path == str(EXAMPLE_WEBP)
    assert args.timer == 3600


def test_playable_filters_animated_vs_static(qapp):
    assert dd.playable(EXAMPLE_WEBP) is True
    assert dd.playable(DEMO_GIF) is True
    assert dd.playable(BANNER_PNG) is False
    assert dd.playable(REPO_ROOT / "README.md") is False
    assert dd.playable(REPO_ROOT / "does_not_exist.webp") is False


def test_resolve_clip_priority_and_memory(qapp, monkeypatch):
    # Bundled example is returned but NOT written to QSettings.
    assert dd.resolve_clip(None, ask=False) == EXAMPLE_WEBP
    assert dd.remembered_clip() is None

    # Explicit path wins and is remembered.
    chosen = dd.resolve_clip(str(DEMO_GIF), ask=False)
    assert chosen == DEMO_GIF.resolve()
    assert dd.remembered_clip() == DEMO_GIF.resolve()

    # Subsequent launch without path returns remembered clip.
    assert dd.resolve_clip(None, ask=False) == DEMO_GIF.resolve()

    # Forgetting clip returns to the example dancer.
    dd.forget_clip()
    assert dd.remembered_clip() is None
    assert dd.resolve_clip(None, ask=False) == EXAMPLE_WEBP

    # Missing example + ask=False returns None cleanly.
    monkeypatch.setattr(dd, "example_clip", lambda: None)
    assert dd.resolve_clip(None, ask=False) is None


def test_load_movie_uses_streaming_cache_and_loops(qapp):
    m = dd.load_movie(EXAMPLE_WEBP)
    assert m.cacheMode() == dd.QMovie.CacheMode.CacheNone
    m.setScaledSize(QSize(270, 180))
    m.start()
    fc = m.frameCount()
    assert fc == 563
    for _ in range(fc + 2):
        assert m.jumpToNextFrame() is True
    assert not m.currentImage().isNull()
    m.stop()

    with pytest.raises(ValueError):
        dd.load_movie(REPO_ROOT / "README.md")


def test_dancer_scaling_preserves_aspect_ratio(qapp):
    dancer = dd.Dancer(EXAMPLE_WEBP)
    try:
        assert dancer.base_size == QSize(1080, 720)
        assert dancer.size() == QSize(540, 360)

        # Tiny portrait clip should not be squashed into a square at low scale.
        dancer.base_size = QSize(200, 400)
        dancer.set_scale(0.1)
        assert dancer.size().height() == dancer.size().width() * 2
        assert max(dancer.size().width(), dancer.size().height()) >= 64
    finally:
        dancer.close()


def test_dancer_click_through_syncs_with_tray_and_respects_no_tray(qapp, monkeypatch):
    # With tray available: middle-click / set_click_through stays in sync with ct_action.
    monkeypatch.setattr(dd.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    dancer = dd.Dancer(EXAMPLE_WEBP, allow_click_through=True)
    tray = dd.TrayController(qapp, dancer)
    try:
        assert tray.ct_action.isEnabled() is True
        assert tray.ct_action.isChecked() is False

        dancer.toggle_click_through()
        assert dancer._click_through is True
        assert tray.ct_action.isChecked() is True

        tray.ct_action.setChecked(False)
        assert dancer._click_through is False
        assert tray.ct_action.isChecked() is False

        # Pause stays synced too.
        dancer.toggle_paused()
        assert dancer._paused is True
        assert tray.pause_action.isChecked() is True
    finally:
        dancer.close()

    # Without tray available: click-through is blocked so user cannot lock themselves out.
    monkeypatch.setattr(dd.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    dancer2 = dd.Dancer(EXAMPLE_WEBP, allow_click_through=False)
    tray2 = dd.TrayController(qapp, dancer2)
    try:
        assert tray2.ct_action.isEnabled() is False
        dancer2.set_click_through(True)
        assert dancer2._click_through is False
    finally:
        dancer2.close()


def test_dancer_use_example_action(qapp, monkeypatch):
    monkeypatch.setattr(dd.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    dancer = dd.Dancer(DEMO_GIF)
    dd.remember_clip(DEMO_GIF)
    tray = dd.TrayController(qapp, dancer)
    try:
        assert tray.example_action.isEnabled() is True
        tray._use_example_clip()
        assert dancer.clip_path.resolve() == EXAMPLE_WEBP.resolve()
        assert dd.remembered_clip() is None
        assert tray.example_action.isEnabled() is False
    finally:
        dancer.close()


def test_dancer_persists_scale_and_clamps_offscreen_position(qapp):
    dancer = dd.Dancer(EXAMPLE_WEBP)
    dancer.set_scale(0.75)
    dancer.move(100, 120)
    dancer.save_state()
    dancer.close()

    # Put an off-screen position in settings and verify clamp brings it back.
    dd.settings().setValue("pos_x", 999999)
    dd.settings().setValue("pos_y", 999999)
    dancer2 = dd.Dancer(EXAMPLE_WEBP)
    try:
        assert abs(dancer2._scale - 0.75) < 1e-3
        assert dancer2.x() < 999999
        assert dancer2.y() < 999999
    finally:
        dancer2.close()


def test_dancer_drag_and_drop_swaps_clip(qapp):
    dancer = dd.Dancer(EXAMPLE_WEBP)
    try:
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(DEMO_GIF))])
        enter_ev = QDragEnterEvent(
            QPoint(10, 10), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        dancer.dragEnterEvent(enter_ev)
        assert enter_ev.isAccepted()

        drop_ev = QDropEvent(
            QPointF(10, 10), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        dancer.dropEvent(drop_ev)
        assert drop_ev.isAccepted()
        assert dancer.clip_path == DEMO_GIF
        assert dd.remembered_clip() == DEMO_GIF
    finally:
        dancer.close()


@pytest.mark.parametrize("size", [QSize(1280, 720), QSize(1920, 1080), QSize(1366, 768)])
def test_lunch_overlay_fits_without_overflow_and_cleans_up(qapp, size):
    dismissed = []
    overlay = dd.LunchOverlay(
        EXAMPLE_WEBP,
        "I'M ON LUNCH",
        "grabbing tacos with the team, back around 1:30pm",
        on_dismiss=lambda: dismissed.append(True),
        timer_seconds=3600,
    )
    overlay.resize(size)
    overlay.show()
    qapp.processEvents()

    # Regression check: overlay must not expand beyond its allocated screen height.
    assert overlay.height() <= size.height()
    assert overlay.width() <= size.width()
    assert "background: transparent" in overlay.dancer_label.styleSheet()
    assert overlay.dancer_label.hasScaledContents() is True
    assert overlay.title_label.wordWrap() is True
    assert overlay.msg_label.wordWrap() is True

    # All visible widgets must sit inside the overlay bounds.
    for widget in (
        overlay.title_label, overlay.msg_label, overlay.timer_label,
        overlay.clock, overlay.dancer_label, overlay.hint,
    ):
        assert widget.isVisible()
        assert widget.geometry().bottom() <= overlay.height()

    # Esc dismisses, stops timer + movie immediately, and deletes overlay on close.
    destroyed = []
    overlay.destroyed.connect(lambda: destroyed.append(True))
    esc = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    overlay.keyPressEvent(esc)
    assert dismissed == [True]
    assert not overlay._clock_timer.isActive()
    assert overlay.movie.state() == dd.QMovie.MovieState.NotRunning
    qapp.processEvents()
    assert destroyed == [True]


def test_lunch_overlay_sign_only_and_screensaver_dismissal(qapp):
    dismissed = []
    overlay = dd.LunchOverlay(
        None, "I'M ON LUNCH", "",
        on_dismiss=lambda: dismissed.append(True),
        screensaver=True,
        timer_seconds=60,
    )
    overlay.resize(1280, 720)
    overlay.show()
    qapp.processEvents()

    assert overlay.movie is None
    assert overlay.dancer_label.isHidden()

    # Any key exits screensaver immediately.
    key = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
    overlay.keyPressEvent(key)
    qapp.processEvents()
    assert dismissed == [True]


def test_lunch_dialog_defaults_and_validation(qapp, monkeypatch):
    dlg = dd.LunchDialog()
    assert dlg.values() == ("I'M ON LUNCH", "", 3600)

    dlg.message_edit.setText("back at 2pm")
    dlg.timer_edit.setText("45m")
    dlg.title_edit.setText("AFK")
    dlg._validate_and_accept()
    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.values() == ("AFK", "back at 2pm", 2700)

    # Invalid duration should warn and keep dialog open.
    warned = []
    monkeypatch.setattr(dd.QMessageBox, "warning", lambda *a, **kw: warned.append(a))
    dlg2 = dd.LunchDialog()
    dlg2.timer_edit.setText("not-a-time")
    dlg2._validate_and_accept()
    assert len(warned) == 1
    assert dlg2.result() != QDialog.DialogCode.Accepted
