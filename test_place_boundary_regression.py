"""place() の境界チェックが、攻撃を防ぎつつ正規の保存先を巻き込まないことを確認する。

想定する正規ケース（Windows実運用）:
  - 保存先の親階層がジャンクション
  - 割り当てネットワークドライブ (Z: -> \\\\server\\share)
  - 8.3短縮名を含むパス
いずれも realpath で別名に解決されるため、abspath/realpath 比較だと全拒否になる。
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
def test_symlinked_destination_root_still_writes(tmp_path):
    """保存先ルート自体がリンク経由でも、out配下に収まるなら書けること（誤検知の回帰テスト）"""
    cache = _make_cache(tmp_path)
    real_out = tmp_path / "real_out"
    real_out.mkdir()
    out = tmp_path / "out_link"
    os.symlink(real_out, out, target_is_directory=True)

    dst = out / "Album" / "2026" / "2026-09"
    ok = engine.place_asset("DCIM/A.JPG", str(cache), str(dst),
                            placed=set(), out_root=str(out))

    assert ok is True
    assert (dst / "A.JPG").exists()
    assert (real_out / "Album" / "2026" / "2026-09" / "A.JPG").exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unavailable")
def test_linkish_parent_still_blocked_with_out_root(tmp_path):
    """main() と同じ呼び方（out_root付き）でも、親リンク越しの脱出は防ぐこと"""
    cache = _make_cache(tmp_path)
    out = tmp_path / "out"
    victim = tmp_path / "victim"
    out.mkdir()
    victim.mkdir()

    os.symlink(victim, out / "Parent", target_is_directory=True)
    dst = out / "Parent" / "Album"

    ok = engine.place_asset("DCIM/A.JPG", str(cache), str(dst),
                            placed=set(), out_root=str(out))

    assert ok is False
    assert not (victim / "Album").exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unavailable")
def test_dst_dir_itself_linkish_still_refused(tmp_path):
    """dst_dir 自身がリンクなら、行き先が out 内でも従来どおり拒否すること（v3.2.2挙動の維持）"""
    cache = _make_cache(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "RealAlbum").mkdir()
    os.symlink(out / "RealAlbum", out / "Alias", target_is_directory=True)

    ok = engine.place_asset("DCIM/A.JPG", str(cache), str(out / "Alias"),
                            placed=set(), out_root=str(out))

    assert ok is False
    assert not (out / "RealAlbum" / "A.JPG").exists()


def test_normal_destination_unaffected(tmp_path):
    """リンクが一切ない通常ケースが従来どおり動くこと"""
    cache = _make_cache(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    dst = out / "Album"

    placed = set()
    ok = engine.place_asset("DCIM/A.JPG", str(cache), str(dst),
                            placed=placed, out_root=str(out))

    assert ok is True
    assert (dst / "A.JPG").exists()
    assert os.path.samefile(cache / "DCIM" / "A.JPG", dst / "A.JPG")  # ハードリンク維持
    assert len(placed) == 1


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unavailable")
def test_prune_not_broken_by_symlinked_root(tmp_path):
    """prune も、保存先ルートがリンク経由なだけで機能停止しないこと"""
    real_out = tmp_path / "real_out"
    real_out.mkdir()
    out = tmp_path / "out_link"
    os.symlink(real_out, out, target_is_directory=True)

    album = out / "Album"
    album.mkdir()
    keep = album / "keep.jpg"
    stray = album / "stray.jpg"
    keep.write_bytes(b"1")
    stray.write_bytes(b"2")

    engine.prune(str(out), {"Album": "k1"}, {"albums": {"k1": "Album"}},
                 {engine._pkey(str(keep))}, [str(album)])

    assert keep.exists()
    assert not stray.exists()
    assert (out / engine.sp("removed") / "Album" / "stray.jpg").exists()
