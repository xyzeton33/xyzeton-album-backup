"""v2.2 レビュー指摘のリグレッションテスト（実機不要）

    python -m pytest -q test_album_export_v23_review.py

ChatGPTによる三次レビューの指摘。v2.3.0 ですべて修正済み。
特に「再接続時に別のiPhoneへ繋がりうる」問題はデータ混在に直結するため重要。
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import album_export as engine


def run(coro):
    return asyncio.run(coro)


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


class FakeLockdown:
    def __init__(self, udid, alive_afc=False):
        self.udid = udid
        self.display_name = udid
        self.product_version = "18.0"
        self.alive_afc = alive_afc
        self.closed = False

    async def close(self):
        self.closed = True


class FakeAFC:
    def __init__(self, alive):
        self.alive = alive

    async def exists(self, path):
        if not self.alive:
            raise ConnectionError("simulated disconnect")
        return True


class FakeAfcService:
    def __init__(self, lockdown):
        self.lockdown = lockdown

    async def __aenter__(self):
        return FakeAFC(self.lockdown.alive_afc)

    async def __aexit__(self, *args):
        return None


def test_reconnect_targets_original_iphone(tmp_path, monkeypatch):
    initial = FakeLockdown("iphone-A", alive_afc=False)
    calls = []

    async def fake_connect():
        return initial

    async def fake_create(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeLockdown("iphone-A", alive_afc=True)

    async def fake_pull(afc, dbdir, refresh=False):
        if not afc.alive:
            raise ConnectionError("disconnect")
        return str(Path(dbdir) / "fake.db")

    async def immediate_wait(reconnect, *args, **kwargs):
        return await reconnect()

    monkeypatch.setattr(engine, "connect", fake_connect)
    monkeypatch.setattr(engine, "create_using_usbmux", fake_create)
    monkeypatch.setattr(engine, "AfcService", FakeAfcService)
    monkeypatch.setattr(engine, "pull_photos_db", fake_pull)
    monkeypatch.setattr(engine, "_wait_reconnect", immediate_wait)
    monkeypatch.setattr(engine, "parse_albums", lambda db: ({}, set(), {}, {}, {}, {}))
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))

    args = argparse.Namespace(
        list=True, out=str(tmp_path), cache=None, skip_pull=False,
        refresh_db=False, db=None, no_date_prefix=False, media_types=[],
        fast_rescan=False, lang="ja", prune=False, gui=False,
    )
    run(engine.run(args))

    assert calls, "reconnect was not attempted"
    _, kwargs = calls[0]
    assert kwargs.get("serial") == "iphone-A"


def test_copy_fallback_is_atomic(tmp_path, monkeypatch):
    src = tmp_path / "source.jpg"
    src.write_bytes(b"ABCDEFGHIJ")
    out = tmp_path / "Album"

    def no_link(a, b):
        raise OSError("hard link unavailable")

    def partial_copy(a, b):
        Path(b).write_bytes(b"ABC")
        raise OSError("simulated disk full during copy")

    monkeypatch.setattr(engine.os, "link", no_link)
    monkeypatch.setattr(engine.shutil, "copy2", partial_copy)

    with pytest.raises(OSError):
        engine.place(str(src), str(out), "tag")

    # A failed fallback copy must never leave a file under the final name.
    assert not (out / "source.jpg").exists()


def _make_case_db(path):
    con = sqlite3.connect(path)
    c = con.cursor()
    c.execute("CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZKIND INTEGER, ZPARENTFOLDER INTEGER, ZUUID TEXT)")
    c.execute("CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZDIRECTORY TEXT, ZFILENAME TEXT)")
    c.execute("CREATE TABLE Z_1ASSETS (Z_1ALBUMS INTEGER, Z_3ASSETS INTEGER)")
    c.executemany("INSERT INTO ZGENERICALBUM VALUES (?,?,?,?,?)", [
        (1, "Album", 2, None, "uuid1"),
        (2, "album", 2, None, "uuid2"),
        (3, "Other", 2, None, "uuid3"),
    ])
    c.executemany("INSERT INTO ZASSET VALUES (?,?,?)", [
        (10, "DCIM/100APPLE", "A.JPG"),
        (11, "DCIM/100APPLE", "B.JPG"),
        (12, "DCIM/100APPLE", "C.JPG"),
    ])
    c.executemany("INSERT INTO Z_1ASSETS VALUES (?,?)", [(1, 10), (2, 11), (3, 12)])
    con.commit()
    con.close()


def test_album_paths_are_unique_case_insensitively(tmp_path, monkeypatch):
    db = tmp_path / "Photos.sqlite"
    _make_case_db(db)
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))
    albums, *_ = engine.parse_albums(str(db))
    keys = [os.path.normpath(p).casefold() for p in albums]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("name", ["CON", "con", "PRN", "AUX", "NUL", "COM1", "LPT1", "NUL.txt"])
def test_safe_avoids_windows_reserved_device_names(name):
    result = engine.safe(name)
    head = result.split(".", 1)[0].upper()
    assert head not in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

def test_probe_closes_lockdown_when_afc_open_fails(monkeypatch):
    import probe

    ld = FakeLockdown("iphone-A", alive_afc=False)

    async def fake_create(*args, **kwargs):
        return ld

    class FailingAfcService:
        def __init__(self, lockdown):
            pass
        async def __aenter__(self):
            raise RuntimeError("simulated AFC open failure")
        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(probe, "create_using_usbmux", fake_create)
    monkeypatch.setattr(probe, "AfcService", FailingAfcService)

    with pytest.raises(RuntimeError):
        run(probe.main())
    assert ld.closed
