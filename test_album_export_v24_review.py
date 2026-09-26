"""v2.3 レビュー指摘のリグレッションテスト（実機不要）

    python -m pytest -q test_album_export_v24_review.py

ChatGPTによる四次レビューの指摘。v2.4.0 ですべて修正済み。
アルバム名の入れ替え（A↔B）でフォルダの中身が混ざる問題が中心。
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import album_export as engine


@pytest.fixture(autouse=True)
def reset_engine():
    engine.CANCEL.clear()
    engine._MADE_DIRS.clear()
    old_log = engine.log
    engine.set_logger(lambda *a, **k: None)
    yield
    engine.CANCEL.clear()
    engine._MADE_DIRS.clear()
    engine.set_logger(old_log)


def test_album_name_swap_is_staged_without_cross_merge(tmp_path):
    out = tmp_path
    (out / "A").mkdir()
    (out / "B").mkdir()
    (out / "A" / "a.txt").write_text("from A", encoding="utf-8")
    (out / "B" / "b.txt").write_text("from B", encoding="utf-8")

    prev = {"albums": {"keyA": "A", "keyB": "B"}}
    # same album IDs, but their display names swapped
    current = {"B": "keyA", "A": "keyB"}

    engine.reconcile_renames(str(out), current, prev)

    assert (out / "A" / "b.txt").exists()
    assert not (out / "A" / "a.txt").exists()
    assert (out / "B" / "a.txt").exists()
    assert not (out / "B" / "b.txt").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows case-insensitive filesystem behavior")
def test_case_only_album_rename_does_not_delete_links(tmp_path):
    out = tmp_path
    (out / "Album").mkdir()
    (out / "Album" / "photo.txt").write_text("keep", encoding="utf-8")

    prev = {"albums": {"key1": "Album"}}
    current = {"album": "key1"}
    engine.reconcile_renames(str(out), current, prev)

    # The file must survive a case-only rename on NTFS.
    candidates = [out / "Album" / "photo.txt", out / "album" / "photo.txt"]
    assert any(p.exists() for p in candidates)


def _make_secondary_collision_db(path: Path):
    con = sqlite3.connect(path)
    c = con.cursor()
    c.execute("CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZKIND INTEGER, ZPARENTFOLDER INTEGER, ZUUID TEXT)")
    c.execute("CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZDIRECTORY TEXT, ZFILENAME TEXT)")
    c.execute("CREATE TABLE Z_1ASSETS (Z_1ALBUMS INTEGER, Z_3ASSETS INTEGER)")
    c.executemany("INSERT INTO ZGENERICALBUM VALUES (?,?,?,?,?)", [
        (1, "A", 2, None, "uuid1"),
        (2, "a", 2, None, "xx000002"),
        (3, "a_000002", 2, None, "uuid3"),
    ])
    c.executemany("INSERT INTO ZASSET VALUES (?,?,?)", [
        (10, "DCIM/100APPLE", "A.JPG"),
        (11, "DCIM/100APPLE", "B.JPG"),
        (12, "DCIM/100APPLE", "C.JPG"),
    ])
    # Process the naturally named suffix target before the album that will generate it.
    c.executemany("INSERT INTO Z_1ASSETS VALUES (?,?)", [(1, 10), (3, 12), (2, 11)])
    con.commit()
    con.close()


def test_album_collision_suffix_is_rechecked_until_unique(tmp_path, monkeypatch):
    db = tmp_path / "Photos.sqlite"
    _make_secondary_collision_db(db)
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))

    albums, *_ = engine.parse_albums(str(db))
    normalized = [os.path.normpath(p).casefold() for p in albums]

    assert len(albums) == 3
    assert len(normalized) == len(set(normalized))


def test_cyclic_album_rename_keeps_each_folder_intact(tmp_path):
    """A→B→C→A のような循環でも中身が混ざらない（2段階renameの検証）"""
    out = tmp_path
    for name, mark in [("A", "a"), ("B", "b"), ("C", "c")]:
        (out / name).mkdir()
        (out / name / f"{mark}.txt").write_text(mark, encoding="utf-8")
    engine.reconcile_renames(str(out),
                             {"B": "k1", "C": "k2", "A": "k3"},
                             {"albums": {"k1": "A", "k2": "B", "k3": "C"}})
    assert (out / "B" / "a.txt").exists()
    assert (out / "C" / "b.txt").exists()
    assert (out / "A" / "c.txt").exists()
    assert not (out / engine.RENAME_TMP).exists()


def test_hardlink_precheck_reports_and_cleans_up(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    out = tmp_path / "out"
    assert engine.check_hardlink(str(cache), str(out)) is True
    assert not list(cache.glob(".hardlink_test*"))
    assert not list(out.glob(".hardlink_test*"))

    def no_link(a, b):
        raise OSError("cross-device link")

    monkeypatch.setattr(engine.os, "link", no_link)
    assert engine.check_hardlink(str(cache), str(out)) is False
    assert not list(cache.glob(".hardlink_test*"))


def test_state_file_is_written_atomically(tmp_path):
    engine.save_state(str(tmp_path), {"Trip": "u1"}, {"albums": {}})
    path = tmp_path / engine.STATE_FILE
    assert path.exists()
    assert not (tmp_path / (engine.STATE_FILE + ".tmp")).exists()
    import json
    assert json.loads(path.read_text(encoding="utf-8"))["albums"] == {"u1": "Trip"}


def test_prune_ignores_windows_case_differences(tmp_path, monkeypatch):
    """Windowsは大文字小文字を区別しないので、綴り違いのパスで
    『置いていないファイル』と誤判定して退避してはいけない。"""
    monkeypatch.setattr(engine.os.path, "normcase", lambda p: p.lower())
    album = tmp_path / "Test"
    album.mkdir()
    f = album / "IMG.HEIC"
    f.write_bytes(b"x")
    placed = {engine._pkey(str(tmp_path / "test" / "IMG.HEIC"))}   # 小文字で記録
    engine.prune(str(tmp_path), {"Test": "u1"}, {"albums": {"u1": "Test"}}, placed, [str(album)])
    assert f.exists()


def test_prune_accepts_raw_paths_on_windows(tmp_path, monkeypatch):
    """placed に生のパス（正規化前）を渡されても誤って退避しない。
    Linuxでは normcase が何もしないため素通りしてしまうので、
    Windows相当の挙動を強制して検証する。"""
    monkeypatch.setattr(engine.os.path, "normcase", lambda p: p.lower())
    album = tmp_path / "Album"
    album.mkdir()
    f = album / "IMG.JPG"
    f.write_bytes(b"abc")
    dropped = engine.prune(str(tmp_path), {"Album": "uuid1"},
                           {"albums": {"uuid1": "Album"}},
                           {str(f)},              # 生のパス（大文字を含む）
                           [str(album)])
    assert dropped == []
    assert f.exists()


def test_prune_sweeps_legacy_flat_unsorted_files(tmp_path):
    """古い版が _未分類 直下に平置きしたファイルも掃除対象にする。
    現在は 年\\年-月 の下に置くため、直下に残っているものは過去の残骸。"""
    out = tmp_path
    legacy = out / engine.sp("unsorted")
    legacy.mkdir()
    stale = legacy / "IMG_1_100A.JPG"
    stale.write_bytes(b"x")
    current_dir = legacy / "2025" / "2025-08"
    current_dir.mkdir(parents=True)
    keep = current_dir / "20250802_030000_IMG_1.JPG"
    keep.write_bytes(b"x")

    engine.prune(str(out), {}, {"albums": {}},
                 {engine._pkey(str(keep))},
                 [str(current_dir), str(legacy)])

    assert not stale.exists()          # 残骸は退避された
    assert keep.exists()               # 今回置いたものは残る
    assert (out / engine.sp("removed")).exists()
