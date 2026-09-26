"""out 配下の途中階層にある symlink/junction を辿らないことの回帰テスト。

保存先ルート自体がリンク経由であることは許可する一方、
ツール管理下の album hierarchy にユーザー作成の link/junction がある場合は
同じ out 内を指していても辿らない、という方針を確認する。
"""
from __future__ import annotations

import os
import pytest

import album_export as engine


def _make_cache(tmp_path):
    cache = tmp_path / "cache"
    (cache / "DCIM").mkdir(parents=True)
    (cache / "DCIM" / "A.JPG").write_bytes(b"PHOTO")
    return cache


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unavailable")
def test_internal_linkish_parent_is_refused(tmp_path):
    cache = _make_cache(tmp_path)
    out = tmp_path / "out"
    real_parent = out / "RealParent"
    real_parent.mkdir(parents=True)

    os.symlink(real_parent, out / "AliasParent", target_is_directory=True)
    dst = out / "AliasParent" / "Album"

    ok = engine.place_asset(
        "DCIM/A.JPG", str(cache), str(dst),
        placed=set(), out_root=str(out),
    )

    assert ok is False
    assert not (real_parent / "Album" / "A.JPG").exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unavailable")
def test_prune_skips_internal_linkish_parent(tmp_path):
    out = tmp_path / "out"
    real_parent = out / "RealParent"
    album = real_parent / "Album"
    album.mkdir(parents=True)

    keep = album / "keep.jpg"
    stray = album / "stray.jpg"
    keep.write_bytes(b"1")
    stray.write_bytes(b"2")

    os.symlink(real_parent, out / "AliasParent", target_is_directory=True)
    managed = out / "AliasParent" / "Album"

    # 実運用と同じく alias 側のパスを placed に入れる。
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
