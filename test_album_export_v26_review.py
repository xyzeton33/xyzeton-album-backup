"""公開直前レビューのリグレッションテスト（実機不要）

    python -m pytest -q test_album_export_v26_review.py

ChatGPTによる六次レビューの指摘。v2.7.0 ですべて修正済み。
・端末からWAL/SHMが消えた場合、取り直し設定に関係なく古い副ファイルを消す
・フォルダ名の衝突解決を「階層ごと」に行う（予約名の親フォルダ、A:B と A?B、Folder と folder）
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import album_export as engine


def run(coro):
    return asyncio.run(coro)


class MainOnlyAFC:
    async def exists(self, path):
        return not (path.endswith("-wal") or path.endswith("-shm"))

    async def stat(self, path):
        return {"st_size": 4}


async def _fake_pull_one(afc, remote, local, label):
    Path(local).write_bytes(b"MAIN")


def test_non_refresh_removes_stale_sidecars_when_remote_set_changed(tmp_path, monkeypatch):
    dbdir = tmp_path / "db"
    dbdir.mkdir()
    (dbdir / "Photos.sqlite").write_bytes(b"MAIN")
    (dbdir / "Photos.sqlite-wal").write_bytes(b"STALE-WAL")
    (dbdir / "Photos.sqlite-shm").write_bytes(b"STALE-SHM")

    monkeypatch.setattr(engine, "pull_one", _fake_pull_one)
    run(engine.pull_photos_db(MainOnlyAFC(), str(dbdir), refresh=False))

    assert not (dbdir / "Photos.sqlite-wal").exists()
    assert not (dbdir / "Photos.sqlite-shm").exists()


def _make_nested_db(path: Path, pairs: list[tuple[str, str]]):
    con = sqlite3.connect(path)
    c = con.cursor()
    c.execute(
        "CREATE TABLE ZGENERICALBUM "
        "(Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZKIND INTEGER, "
        " ZPARENTFOLDER INTEGER, ZUUID TEXT)"
    )
    c.execute(
        "CREATE TABLE ZASSET "
        "(Z_PK INTEGER PRIMARY KEY, ZDIRECTORY TEXT, ZFILENAME TEXT)"
    )
    c.execute(
        "CREATE TABLE Z_1ASSETS "
        "(Z_1ALBUMS INTEGER, Z_3ASSETS INTEGER)"
    )

    folder_pk = 1
    album_pk = 100
    asset_pk = 1000
    for folder_name, album_name in pairs:
        c.execute(
            "INSERT INTO ZGENERICALBUM VALUES (?,?,?,?,?)",
            (folder_pk, folder_name, 4000, None, f"folder-{folder_pk:04d}")
        )
        c.execute(
            "INSERT INTO ZGENERICALBUM VALUES (?,?,?,?,?)",
            (album_pk, album_name, 2, folder_pk, f"album-{album_pk:04d}")
        )
        # find_join_table() needs >= 3 rows.
        for _ in range(3):
            c.execute(
                "INSERT INTO ZASSET VALUES (?,?,?)",
                (asset_pk, "DCIM/100APPLE", f"{asset_pk}.JPG")
            )
            c.execute(
                "INSERT INTO Z_1ASSETS VALUES (?,?)",
                (album_pk, asset_pk)
            )
            asset_pk += 1
        folder_pk += 1
        album_pk += 1

    con.commit()
    con.close()


def _root_key(path: str) -> str:
    return os.path.normpath(path).split(os.sep, 1)[0].casefold()


@pytest.mark.parametrize("reserved_root", [
    "_cache_DCIM",
    "_album_state.json",
    "_rename_tmp",
    "_削除済み",
    "_MediaTypes",
])
def test_reserved_parent_folder_is_renamed_at_root(tmp_path, monkeypatch, reserved_root):
    db = tmp_path / "Photos.sqlite"
    _make_nested_db(db, [(reserved_root, "Child")])
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))

    albums, *_ = engine.parse_albums(str(db))
    internal = engine.internal_names()

    assert albums
    for p in albums:
        assert _root_key(p) not in internal, p


@pytest.mark.parametrize("pairs", [
    [("A:B", "One"), ("A?B", "Two")],
    [("Folder", "One"), ("folder", "Two")],
])
def test_distinct_parent_folders_stay_distinct_under_windows_semantics(tmp_path, monkeypatch, pairs):
    db = tmp_path / "Photos.sqlite"
    _make_nested_db(db, pairs)
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))

    albums, *_ = engine.parse_albums(str(db))
    roots = [_root_key(p) for p in albums]

    assert len(set(roots)) == 2, roots


def test_nested_structure_resolves_every_level(tmp_path, monkeypatch):
    """予約名の親・禁止文字衝突・同名アルバムが同時に存在しても、階層ごとに解決される"""
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))
    db = tmp_path / "Photos.sqlite"
    con = sqlite3.connect(db)
    c = con.cursor()
    c.executescript("""CREATE TABLE ZASSET(Z_PK INTEGER PRIMARY KEY,ZDIRECTORY TEXT,ZFILENAME TEXT,ZTRASHEDSTATE INTEGER DEFAULT 0);
    CREATE TABLE ZGENERICALBUM(Z_PK INTEGER PRIMARY KEY,ZTITLE TEXT,ZKIND INTEGER,ZTRASHEDSTATE INTEGER DEFAULT 0,ZPARENTFOLDER INTEGER,ZUUID TEXT);
    CREATE TABLE Z_1ASSETS(Z_1ALBUMS INTEGER,Z_3ASSETS INTEGER);""")
    c.execute("INSERT INTO ZGENERICALBUM VALUES(1,NULL,3999,0,NULL,'root')")
    for r in [(10, "Fam", 4000, 0, 1, "f-aaa"), (11, "_cache_DCIM", 4000, 0, 1, "f-bbb"),
              (12, "A:B", 4000, 0, 1, "f-ccc"), (13, "A?B", 4000, 0, 1, "f-ddd"),
              (20, "Sports", 2, 0, 10, "a-111"), (21, "Kids", 2, 0, 11, "a-222"),
              (22, "ONE", 2, 0, 12, "a-333"), (23, "TWO", 2, 0, 13, "a-444"),
              (24, "Trip", 2, 0, 1, "a-555"), (25, "Trip", 2, 0, 1, "a-666")]:
        c.execute("INSERT INTO ZGENERICALBUM VALUES(?,?,?,?,?,?)", r)
    pk = 1000
    for alb in (20, 21, 22, 23, 24, 25):
        for _ in range(3):
            c.execute("INSERT INTO ZASSET VALUES(?,?,?,?)", (pk, "DCIM/100A", f"{pk}.JPG", 0))
            c.execute("INSERT INTO Z_1ASSETS VALUES(?,?)", (alb, pk))
            pk += 1
    con.commit()
    con.close()

    albums, *_ = engine.parse_albums(str(db))
    assert len(albums) == 6
    internal = engine.internal_names()
    roots = {os.path.normcase(p.split(os.sep, 1)[0]).casefold() for p in albums}
    assert not (roots & internal)
    tops = {p.split(os.sep)[0] for p in albums if os.sep in p}
    assert len(tops) == 4        # 親フォルダ4つが別々に保たれる
