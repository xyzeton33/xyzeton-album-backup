"""Windows専用: NTFSジャンクション版の内部リンク回帰テスト。
symlink作成には管理者権限/開発者モードが要るが、ジャンクションは一般ユーザーでも作れるため、
CI/一般ユーザー環境でもこちらは skip されずに実行される想定。
"""
from __future__ import annotations
import os
import sys
import subprocess
import pytest

import album_export as engine

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="NTFS junction is Windows-only")


def _make_junction(link, target):
    # mklink /J はシェル組み込みのため cmd.exe 経由。os.symlink と違い管理者権限は不要。
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True, capture_output=True,
    )


def _make_cache(tmp_path):
    cache = tmp_path / "cache"
    (cache / "DCIM").mkdir(parents=True)
    (cache / "DCIM" / "A.JPG").write_bytes(b"PHOTO")
    return cache


def test_internal_junction_parent_is_refused(tmp_path):
    cache = _make_cache(tmp_path)
    out = tmp_path / "out"
    real_parent = out / "RealParent"
    real_parent.mkdir(parents=True)

    _make_junction(out / "AliasParent", real_parent)
    dst = out / "AliasParent" / "Album"

    ok = engine.place_asset(
        "DCIM/A.JPG", str(cache), str(dst),
        placed=set(), out_root=str(out),
    )

    assert ok is False
    assert not (real_parent / "Album" / "A.JPG").exists()


def test_root_itself_via_junction_still_allowed(tmp_path):
    cache = _make_cache(tmp_path)
    real_out = tmp_path / "real_out"
    real_out.mkdir()
    link_out = tmp_path / "link_out"
    _make_junction(link_out, real_out)

    ok = engine.place_asset(
        "DCIM/A.JPG", str(cache), str(link_out / "Alb"),
        placed=set(), out_root=str(link_out),
    )

    assert ok is True
    assert (real_out / "Alb" / "A.JPG").exists()


def test_prune_skips_internal_junction_parent(tmp_path):
    out = tmp_path / "out"
    real_parent = out / "RealParent"
    album = real_parent / "Album"
    album.mkdir(parents=True)

    keep = album / "keep.jpg"
    stray = album / "stray.jpg"
    keep.write_bytes(b"1")
    stray.write_bytes(b"2")

    _make_junction(out / "AliasParent", real_parent)
    managed = out / "AliasParent" / "Album"

    engine.prune(
        str(out),
        {"AliasParent/Album": "k1"},
        {"albums": {"k1": "AliasParent/Album"}},
        {engine._pkey(str(managed / "keep.jpg"))},
        [str(managed)],
    )

    assert keep.exists()
    assert stray.exists()
    assert not (out / engine.sp("removed") / "AliasParent" / "Album" / "stray.jpg").exists()
