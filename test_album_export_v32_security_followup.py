"""iPhone Album Backup security follow-up tests（no real iPhone required）

別モデルによるセキュリティレビューの四次指摘（v3.2.0時点）。v3.2.1ですべて修正済み。
固定名の一時ファイル・symlink/junction経由の境界抜け・壊れたstateへの耐性を確認する。

Run:
    python -m pytest -q test_album_export_v32_security_followup.py
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

import album_export as engine


def _can_create_symlinks():
    """os.symlink が『存在するか』ではなく『実際に使えるか』を確認する。
    Windowsでは関数自体は常に存在するが、管理者権限または開発者モードが
    無いと WinError 1314 で失敗する。存在チェックだけの skipif だと、
    多くの利用者のPCでテストが失敗扱いになってしまう。"""
    if not hasattr(os, "symlink"):
        return False
    try:
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "target")
            os.makedirs(target)
            os.symlink(target, os.path.join(d, "link"), target_is_directory=True)
        return True
    except OSError:
        return False


_SYMLINK_OK = _can_create_symlinks()
_SYMLINK_SKIP_REASON = (
    "このPCではシンボリックリンクを作成できません"
    "（管理者権限で実行するか、設定→更新とセキュリティ→開発者向け→開発者モード をオンにすると実行できます）"
)


def test_app_dir_probe_does_not_delete_preexisting_file(tmp_path, monkeypatch):
    """The writeability probe must not overwrite/delete a user's existing .write_test."""
    marker = tmp_path / ".write_test"
    marker.write_bytes(b"USER-DATA")

    monkeypatch.setattr(engine, "_APP_DIR", None)
    monkeypatch.setattr(engine, "_exe_dir", lambda: str(tmp_path))

    assert engine.app_dir() == str(tmp_path)
    assert marker.exists()
    assert marker.read_bytes() == b"USER-DATA"


def test_copy_fallback_does_not_overwrite_preexisting_copying_file(tmp_path, monkeypatch):
    """Copy fallback must not reuse a fixed *.copying name owned by somebody else."""
    src = tmp_path / "source.bin"
    dst_dir = tmp_path / "album"
    dst_dir.mkdir()
    src.write_bytes(b"SOURCE")

    marker = dst_dir / "source.bin.copying"
    marker.write_bytes(b"USER-DATA")

    def fail_link(*args, **kwargs):
        raise OSError("force copy fallback")

    monkeypatch.setattr(os, "link", fail_link)

    placed = engine.place(str(src), str(dst_dir), "x")
    assert placed is not None
    assert marker.exists()
    assert marker.read_bytes() == b"USER-DATA"


@pytest.mark.skipif(not _SYMLINK_OK, reason=_SYMLINK_SKIP_REASON)
def test_safe_cache_path_rejects_symlink_escape(tmp_path):
    """A cache child link/junction that points outside cache must not expose external files."""
    cache = tmp_path / "cache"
    victim = tmp_path / "victim"
    cache.mkdir()
    victim.mkdir()
    (victim / "secret.jpg").write_bytes(b"SECRET")

    os.symlink(victim, cache / "DCIM", target_is_directory=True)

    assert engine.safe_cache_path(str(cache), "DCIM/secret.jpg") is None


@pytest.mark.skipif(not _SYMLINK_OK, reason=_SYMLINK_SKIP_REASON)
def test_place_asset_does_not_write_through_output_symlink(tmp_path):
    """A crafted album directory link/junction must not redirect output outside backup root."""
    cache = tmp_path / "cache"
    (cache / "DCIM").mkdir(parents=True)
    (cache / "DCIM" / "A.JPG").write_bytes(b"PHOTO")

    out = tmp_path / "out"
    victim = tmp_path / "victim"
    out.mkdir()
    victim.mkdir()
    os.symlink(victim, out / "Album", target_is_directory=True)

    ok = engine.place_asset("DCIM/A.JPG", str(cache), str(out / "Album"), placed=set())

    assert ok is False
    assert not (victim / "A.JPG").exists()


@pytest.mark.skipif(not _SYMLINK_OK, reason=_SYMLINK_SKIP_REASON)
def test_prune_does_not_follow_nested_symlink(tmp_path):
    """Merge/prune must never recurse through a nested link/junction into an external directory."""
    out = tmp_path / "out"
    album = out / "Album"
    album.mkdir(parents=True)

    victim = tmp_path / "victim"
    victim.mkdir()
    keep = victim / "KEEP.txt"
    keep.write_text("do not move", encoding="utf-8")

    os.symlink(victim, album / "nested", target_is_directory=True)

    # Make destination exist so _move_merge() takes the recursive merge path.
    (out / engine.sp("removed") / "Album" / "nested").mkdir(parents=True)

    engine.prune(
        str(out),
        {},
        {"albums": {"old-key": "Album"}},
        set(),
        [],
    )

    assert keep.exists()


def test_malformed_state_shape_is_treated_as_empty(tmp_path):
    """Malformed/tampered state should not crash the backup."""
    p = tmp_path / engine.STATE_FILE
    p.write_text('{"albums": [], "special": "not-a-dict"}', encoding="utf-8")

    state = engine.load_state(str(tmp_path))

    assert isinstance(state, dict)
    assert isinstance(state.get("albums", {}), dict)
    assert isinstance(state.get("special", {}), dict)
