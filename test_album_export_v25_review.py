"""公開前レビューのリグレッションテスト（実機不要）

ChatGPTによる五次レビューの指摘。v2.6.0 ですべて修正済み。

対象:
1) Photos.sqlite の -wal/-shm が端末側で消えた時、古いローカル副ファイルを残さないこと
2) ユーザーのアルバム名がツール内部の予約パスと衝突しないこと

実行例:
    python -m pytest -q test_album_export_v25_release_followup.py
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import album_export as engine


def run(coro):
    return asyncio.run(coro)


class MainOnlyAFC:
    """Photos.sqlite はあるが -wal/-shm は端末側に存在しない状態。"""
    async def exists(self, path):
        return not (path.endswith("-wal") or path.endswith("-shm"))

    async def stat(self, path):
        return {"st_size": 4}


async def _fake_pull_one(afc, remote, local, label):
    Path(local).write_bytes(b"MAIN")


def test_refresh_removes_stale_sqlite_sidecars(tmp_path, monkeypatch):
    """refresh時、端末に無い古い WAL/SHM を前回分から持ち越してはいけない。"""
    dbdir = tmp_path / "db"
    dbdir.mkdir()
    (dbdir / "Photos.sqlite").write_bytes(b"OLD!")
    (dbdir / "Photos.sqlite-wal").write_bytes(b"STALE-WAL")
    (dbdir / "Photos.sqlite-shm").write_bytes(b"STALE-SHM")

    monkeypatch.setattr(engine, "pull_one", _fake_pull_one)
    run(engine.pull_photos_db(MainOnlyAFC(), str(dbdir), refresh=True))

    assert (dbdir / "Photos.sqlite").read_bytes() == b"MAIN"
    assert not (dbdir / "Photos.sqlite-wal").exists()
    assert not (dbdir / "Photos.sqlite-shm").exists()


def _make_db(path: Path, names: list[str]):
    con = sqlite3.connect(path)
    c = con.cursor()
    c.execute("CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZKIND INTEGER, ZPARENTFOLDER INTEGER, ZUUID TEXT)")
    c.execute("CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZDIRECTORY TEXT, ZFILENAME TEXT)")
    c.execute("CREATE TABLE Z_1ASSETS (Z_1ALBUMS INTEGER, Z_3ASSETS INTEGER)")
    for i, name in enumerate(names, 1):
        c.execute("INSERT INTO ZGENERICALBUM VALUES (?,?,?,?,?)", (i, name, 2, None, f"uuid{i}"))
        c.execute("INSERT INTO ZASSET VALUES (?,?,?)", (100 + i, "DCIM/100APPLE", f"{i}.JPG"))
        c.execute("INSERT INTO Z_1ASSETS VALUES (?,?)", (i, 100 + i))
    con.commit()
    con.close()


def test_user_album_roots_do_not_collide_with_internal_paths(tmp_path, monkeypatch):
    """内部フォルダ/レポート名と同名のユーザーアルバムは別名へ退避されるべき。"""
    reserved = {
        "_cache_dcim",
        "_rename_tmp",
        "_album_state.json",
        "_未分類",
        "_unsorted",
        "_削除済み",
        "_removed",
        "_メディアタイプ",
        "_mediatypes",
        "_取得失敗一覧.txt",
        "_failed_downloads.txt",
        "_icloudにしか無い写真.txt",
        "_cloud_only_photos.txt",
        "_メディアタイプ診断.txt",
        "_media_type_diagnostics.txt",
    }
    names = [
        "_cache_DCIM", "_rename_tmp", "_album_state.json", "_削除済み",
        "_Removed", "_未分類", "_MediaTypes", "_failed_downloads.txt",
        "_cloud_only_photos.txt", "_media_type_diagnostics.txt",
    ]
    db = tmp_path / "Photos.sqlite"
    _make_db(db, names)
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))

    albums, *_ = engine.parse_albums(str(db))
    roots = {os.path.normpath(p).split(os.sep, 1)[0].casefold() for p in albums}
    assert not (roots & reserved), f"internal path collision: {sorted(roots & reserved)}"


def test_stale_wal_would_shadow_a_fresh_database(tmp_path):
    """なぜWAL/SHMを1セットで扱う必要があるかの根拠。
    新しいmain DBに古いWALが同居すると、古い内容が読み出される。"""
    import shutil
    old = tmp_path / "old.sqlite"
    con = sqlite3.connect(old)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE ZGENERICALBUM(Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT)")
    con.execute("INSERT INTO ZGENERICALBUM VALUES(1,'OLD')")
    con.commit()
    stale_wal = tmp_path / "stale-wal"
    if (tmp_path / "old.sqlite-wal").exists():
        shutil.copy(tmp_path / "old.sqlite-wal", stale_wal)
    con.close()

    fresh = tmp_path / "fresh.sqlite"
    c = sqlite3.connect(fresh)
    c.execute("CREATE TABLE ZGENERICALBUM(Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT)")
    c.execute("INSERT INTO ZGENERICALBUM VALUES(1,'NEW')")
    c.commit()
    c.close()

    mixed = tmp_path / "mixed.sqlite"
    shutil.copy(fresh, mixed)
    if stale_wal.exists():
        shutil.copy(stale_wal, str(mixed) + "-wal")
        con3 = sqlite3.connect(f"file:{mixed}?mode=ro", uri=True)
        got = con3.execute("SELECT ZTITLE FROM ZGENERICALBUM").fetchone()[0]
        con3.close()
        assert got == "OLD"      # 古いWALが勝つ = これを防ぐのが pull_photos_db の役目


def test_reused_database_keeps_the_whole_set(tmp_path, monkeypatch):
    """端末側と同じ構成なら再取得しない（高速化を壊していないことの確認）"""
    dbdir = tmp_path / "db"
    dbdir.mkdir()
    (dbdir / "Photos.sqlite").write_bytes(b"MAIN")

    class SameAFC:
        async def exists(self, path):
            return not (path.endswith("-wal") or path.endswith("-shm"))
        async def stat(self, path):
            return {"st_size": 4}

    called = []

    async def spy(afc, remote, local, label):
        called.append(remote)

    monkeypatch.setattr(engine, "pull_one", spy)
    run(engine.pull_photos_db(SameAFC(), str(dbdir), refresh=False))
    assert called == []          # 取り直していない


def _dup_name_db(path, reverse_links=False):
    con = sqlite3.connect(path)
    c = con.cursor()
    c.executescript("""CREATE TABLE ZASSET(Z_PK INTEGER PRIMARY KEY,ZDIRECTORY TEXT,ZFILENAME TEXT,ZTRASHEDSTATE INTEGER DEFAULT 0);
    CREATE TABLE ZGENERICALBUM(Z_PK INTEGER PRIMARY KEY,ZTITLE TEXT,ZKIND INTEGER,ZTRASHEDSTATE INTEGER DEFAULT 0,ZPARENTFOLDER INTEGER,ZUUID TEXT);
    CREATE TABLE Z_1ASSETS(Z_1ALBUMS INTEGER,Z_3ASSETS INTEGER);""")
    c.execute("INSERT INTO ZGENERICALBUM VALUES(1,NULL,3999,0,NULL,'root')")
    c.execute("INSERT INTO ZGENERICALBUM VALUES(10,'Same',2,0,1,'AAAA-1111')")
    c.execute("INSERT INTO ZGENERICALBUM VALUES(11,'Same',2,0,1,'BBBB-4D4940')")
    c.executemany("INSERT INTO ZASSET VALUES(?,?,?,?)",
                  [(100 + i, "DCIM/100A", f"a{i}.JPG", 0) for i in range(6)])
    links = [(10, 100), (10, 101), (10, 102), (11, 103), (11, 104), (11, 105)]
    if reverse_links:
        links = list(reversed(links))
    c.executemany("INSERT INTO Z_1ASSETS VALUES(?,?)", links)
    con.commit()
    con.close()


def test_duplicate_album_names_get_stable_folders(tmp_path, monkeypatch):
    """同名アルバムがある時、どちらが素の名前を取るかは実行ごとに変わってはいけない。
    変わると中身が入れ替わり、片方がまるごと _削除済み に退避されてしまう。"""
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))
    results = []
    for i, rev in enumerate((False, True)):
        db = tmp_path / f"P{i}.sqlite"
        _dup_name_db(db, reverse_links=rev)
        albums, _, _, keys, _, _ = engine.parse_albums(str(db))
        results.append({keys[p]: p for p in albums})
    assert results[0] == results[1]
    assert set(results[0]) == {"AAAA-1111", "BBBB-4D4940"}
