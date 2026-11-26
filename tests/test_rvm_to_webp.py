"""Tests for rvm_to_webp.py argument validation, commands, and error handling."""
from types import SimpleNamespace
import pytest

import rvm_to_webp as rtw


def test_validate_args_and_commands(tmp_path):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.webp"

    args = rtw.parse_args([str(src), str(dst), "1280", "720", "25", "0", "10"])
    rtw.validate_args(args)

    dec_cmd = rtw.build_decode_cmd(args)
    assert "-vf" in dec_cmd
    assert "scale=1280:720:flags=lanczos" in dec_cmd
    assert dec_cmd[0] == "ffmpeg"

    enc_cmd = rtw.build_encode_cmd(args)
    assert "libwebp_anim" in enc_cmd
    assert "1280x720" in enc_cmd
    assert str(dst) == enc_cmd[-1]


def test_validate_args_rejects_invalid(tmp_path):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.webp"

    with pytest.raises(ValueError, match="not found"):
        rtw.validate_args(rtw.parse_args([str(tmp_path / "missing.mp4"), str(dst), "640", "360", "25", "0", "5"]))

    with pytest.raises(ValueError, match="positive"):
        rtw.validate_args(rtw.parse_args([str(src), str(dst), "0", "360", "25", "0", "5"]))

    with pytest.raises(ValueError, match="alpha-low"):
        rtw.validate_args(rtw.parse_args([str(src), str(dst), "640", "360", "25", "0", "5", "--alpha-low", "0.6", "--alpha-high", "0.5"]))

    with pytest.raises(ValueError, match="Quality"):
        rtw.validate_args(rtw.parse_args([str(src), str(dst), "640", "360", "25", "0", "5", "--quality", "101"]))


def test_select_device():
    fake_cuda = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)),
    )
    assert rtw.select_device("auto", fake_cuda) == "cuda"
    assert rtw.select_device("cpu", fake_cuda) == "cpu"

    fake_cpu = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)),
    )
    assert rtw.select_device("auto", fake_cpu) == "cpu"
    with pytest.raises(RuntimeError, match="CUDA"):
        rtw.select_device("cuda", fake_cpu)


def test_main_errors_cleanly_when_ffmpeg_missing(tmp_path, monkeypatch):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    monkeypatch.setattr(rtw.shutil, "which", lambda _: None)
    with pytest.raises(SystemExit, match="ffmpeg not found"):
        rtw.main([str(src), str(tmp_path / "out.webp"), "640", "360", "25", "0", "5"])
