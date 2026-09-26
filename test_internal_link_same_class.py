"""フィードバック6の指摘と同じ種類（out 内部を指す途中リンク）を、
state 由来の経路を扱う他の関数でも辿らないことの確認。"""
from __future__ import annotations
import os, pytest
import album_export as engine

needs_symlink = pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unavailable")

def _alias(out):
    real = out / "RealParent" / "Album"
    real.mkdir(parents=True)
    (real / "x.jpg").write_bytes(b"1")
    os.symlink(out / "RealParent", out / "AliasParent", target_is_directory=True)
    return real

@needs_symlink
def test_prune_album_gone_skips_internal_linkish_parent(tmp_path):
    out = tmp_path / "out"; real = _alias(out)
    engine.prune(str(out), {}, {"albums": {"k1": "AliasParent/Album"}}, set(), [])
    assert (real / "x.jpg").exists()

@needs_symlink
def test_reconcile_renames_skips_internal_linkish_parent(tmp_path):
    out = tmp_path / "out"; real = _alias(out)
    engine.reconcile_renames(str(out), {"New": "k1"}, {"albums": {"k1": "AliasParent/Album"}})
    assert (real / "x.jpg").exists()
    assert not (out / "New").exists()

@needs_symlink
def test_reconcile_special_skips_internal_linkish_special_dir(tmp_path):
    # 旧言語の特殊フォルダ(_Unsorted)の位置に、out 内の別フォルダを指すリンクがある
    out = tmp_path / "out"
    real = out / "UserFolder"; real.mkdir(parents=True)
    (real / "x.jpg").write_bytes(b"1")
    os.symlink(real, out / "_Unsorted", target_is_directory=True)
    old = engine.special_names()  # 現在 ja
    prev = {"special": dict(old, unsorted="_Unsorted")}
    engine.reconcile_special(str(out), prev)
    assert (real / "x.jpg").exists()

@needs_symlink
def test_root_itself_via_link_still_allowed(tmp_path):
    cache = tmp_path / "cache"; (cache / "DCIM").mkdir(parents=True)
    (cache / "DCIM" / "A.JPG").write_bytes(b"P")
    real_out = tmp_path / "real_out"; real_out.mkdir()
    link_out = tmp_path / "link_out"
    os.symlink(real_out, link_out, target_is_directory=True)
    ok = engine.place_asset("DCIM/A.JPG", str(cache), str(link_out / "Alb"), placed=set(), out_root=str(link_out))
    assert ok is True and (real_out / "Alb" / "A.JPG").exists()

def test_normal_nested_path_still_allowed(tmp_path):
    cache = tmp_path / "cache"; (cache / "DCIM").mkdir(parents=True)
    (cache / "DCIM" / "A.JPG").write_bytes(b"P")
    out = tmp_path / "out"
    ok = engine.place_asset("DCIM/A.JPG", str(cache), str(out / "Folder" / "Alb"), placed=set(), out_root=str(out))
    assert ok is True and (out / "Folder" / "Alb" / "A.JPG").exists()

@needs_symlink
def test_reconcile_special_skips_type_dir_under_linkish_media(tmp_path):
    # 旧 media フォルダ(_Media Types)自体がリンク → その配下の種類フォルダ移動も辿らない
    out = tmp_path / "out"
    real = out / "UserFolder" / "Selfies"; real.mkdir(parents=True)
    (real / "x.jpg").write_bytes(b"1")
    engine.set_language("en"); en = engine.special_names(); engine.set_language("ja")
    os.symlink(out / "UserFolder", out / en["media"], target_is_directory=True)
    prev = {"special": en}
    engine.reconcile_special(str(out), prev)
    assert (real / "x.jpg").exists()

@needs_symlink
def test_reconcile_renames_refuses_linkish_destination(tmp_path):
    # 改名先（今回のアルバム名由来）の途中階層が out 内部を指すリンク
    out = tmp_path / "out"
    (out / "Old").mkdir(parents=True); (out / "Old" / "x.jpg").write_bytes(b"1")
    (out / "RealParent").mkdir()
    os.symlink(out / "RealParent", out / "AliasParent", target_is_directory=True)
    engine.reconcile_renames(str(out), {"AliasParent/Album": "k1"}, {"albums": {"k1": "Old"}})
    assert not (out / "RealParent" / "Album").exists()
    assert (out / "Old" / "x.jpg").exists()   # 動かさずに元の場所に残す

@needs_symlink
def test_reconcile_special_refuses_linkish_destination(tmp_path):
    out = tmp_path / "out"
    engine.set_language("en"); en = engine.special_names(); engine.set_language("ja")
    (out / en["unsorted"]).mkdir(parents=True); (out / en["unsorted"] / "x.jpg").write_bytes(b"1")
    (out / "UserFolder").mkdir()
    ja = engine.special_names()
    os.symlink(out / "UserFolder", out / ja["unsorted"], target_is_directory=True)
    engine.reconcile_special(str(out), {"special": en})
    assert not (out / "UserFolder" / "x.jpg").exists()
