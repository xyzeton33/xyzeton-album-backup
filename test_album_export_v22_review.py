"""v2.1 レビュー指摘（7件）のリグレッションテスト

    python -m pytest -q test_album_export_v22_review.py

ChatGPTによる二次レビューで指摘された内容。v2.2.0 ですべて修正済み。
"""
import argparse
import asyncio
import errno
import os
import sqlite3
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import album_export as engine


def run(c): return asyncio.run(c)

class AliveAFC:
    async def exists(self, path): return True


def test_pull_dcim_must_propagate_local_io_error(tmp_path, monkeypatch):
    async def fail_download(*a, **k):
        raise engine.LocalIOError('disk full', errno.ENOSPC)
    monkeypatch.setattr(engine, 'download', fail_download)
    with pytest.raises(engine.LocalIOError):
        run(engine.pull_dcim(AliveAFC(), str(tmp_path/'cache'), [('DCIM/A.JPG', 10)], str(tmp_path)))


def test_prune_preserves_different_same_name_destination(tmp_path):
    album = tmp_path/'Album'; album.mkdir()
    removed = tmp_path/engine.sp('removed')/'Album'; removed.mkdir(parents=True)
    src = album/'IMG.JPG'; src.write_bytes(b'SOURCE')
    dst = removed/'IMG.JPG'; dst.write_bytes(b'OLD-REMOVED')
    engine.prune(str(tmp_path), {'Album':'uuid'}, {'albums': {'uuid':'Album'}}, set(), [str(album)])
    payloads = sorted(p.read_bytes() for p in removed.iterdir() if p.is_file())
    assert payloads == [b'OLD-REMOVED', b'SOURCE']


class OneFileAFC:
    def __init__(self, remote_size): self.remote_size=remote_size; self.stat_calls=[]
    async def listdir(self, path):
        return ['100APPLE'] if path=='DCIM' else ['IMG_0001.JPG']
    async def stat(self, path):
        self.stat_calls.append(path)
        if path=='DCIM/100APPLE': return {'st_ifmt':'S_IFDIR','st_size':0}
        return {'st_ifmt':'S_IFREG','st_size':self.remote_size}


def test_scan_remote_verifies_remote_size_by_default(tmp_path):
    """既定（cacheを渡さない）ではリモートのサイズを必ず確認する"""
    cache = tmp_path/'cache'
    p = cache/'DCIM'/'100APPLE'/'IMG_0001.JPG'; p.parent.mkdir(parents=True); p.write_bytes(b'OLD')
    afc = OneFileAFC(remote_size=9)
    files = run(engine.scan_remote(afc, 'DCIM'))
    assert files == [('DCIM/100APPLE/IMG_0001.JPG', 9)]


def test_scan_remote_fast_mode_trusts_cache_when_explicitly_requested(tmp_path):
    """--fast-rescan 相当（cacheを渡す）でのみローカルを信用して往復を省く"""
    cache = tmp_path/'cache'
    p = cache/'DCIM'/'100APPLE'/'IMG_0001.JPG'; p.parent.mkdir(parents=True); p.write_bytes(b'OLD')
    afc = OneFileAFC(remote_size=9)
    files = run(engine.scan_remote(afc, 'DCIM', str(cache), {}))
    assert files == [('DCIM/100APPLE/IMG_0001.JPG', 3)]
    assert 'DCIM/100APPLE/IMG_0001.JPG' not in afc.stat_calls


class BytesAFC:
    def __init__(self, data=b'abcdef'): self.data=data; self.off=0; self.open_calls=0
    async def fopen(self, *a): self.open_calls +=1; self.off=0; return 1
    async def fseek(self,h,o,w): self.off=o
    async def fread(self,h,n):
        b=self.data[self.off:self.off+n]; self.off += len(b); return b
    async def fclose(self,h): pass


def test_replace_disk_full_is_local_fatal_without_redownload(tmp_path, monkeypatch):
    dst = tmp_path/'IMG.JPG'; afc=BytesAFC()
    real_replace = os.replace
    def fail_replace(src, dst): raise OSError(errno.ENOSPC, 'disk full finalize')
    async def no_sleep(_): pass
    monkeypatch.setattr(engine.os, 'replace', fail_replace)
    monkeypatch.setattr(engine.asyncio, 'sleep', no_sleep)
    with pytest.raises(engine.LocalIOError):
        run(engine.download(afc, 'DCIM/IMG.JPG', str(dst), 6, retries=3))
    assert afc.open_calls == 1


def test_download_recreates_cached_directory_if_made_dirs_is_stale(tmp_path):
    d = tmp_path/'gone'; engine._MADE_DIRS.add(str(d))
    afc=BytesAFC(b'abc')
    dst=d/'IMG.JPG'
    try:
        changed=run(engine.download(afc,'DCIM/IMG.JPG',str(dst),3,retries=1))
        assert changed and dst.read_bytes()==b'abc'
    finally:
        engine._MADE_DIRS.discard(str(d))


def make_collision_db(path):
    con=sqlite3.connect(path); c=con.cursor()
    c.execute('CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZKIND INTEGER, ZPARENTFOLDER INTEGER, ZUUID TEXT)')
    c.execute('CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZDIRECTORY TEXT, ZFILENAME TEXT)')
    c.execute('CREATE TABLE Z_1ASSETS (Z_1ALBUMS INTEGER, Z_3ASSETS INTEGER)')
    c.executemany('INSERT INTO ZGENERICALBUM VALUES (?,?,?,?,?)', [
        (1,'A:B',2,None,'u1'), (2,'A?B',2,None,'u2'), (3,'Other',2,None,'u3')])
    c.executemany('INSERT INTO ZASSET VALUES (?,?,?)', [
        (10,'DCIM/100APPLE','A.JPG'), (11,'DCIM/100APPLE','B.JPG'), (12,'DCIM/100APPLE','C.JPG')])
    c.executemany('INSERT INTO Z_1ASSETS VALUES (?,?)', [(1,10),(2,11),(3,12)])
    con.commit(); con.close()


def test_sanitized_album_name_collision_does_not_merge_distinct_albums(tmp_path, monkeypatch):
    db=tmp_path/'Photos.sqlite'; make_collision_db(db)
    monkeypatch.setattr(engine, 'app_dir', lambda: str(tmp_path))
    albums, _, _, keys, _, _ = engine.parse_albums(str(db))
    assert len(albums)==3
    assert len(keys)==3
    assert set(keys.values())=={'u1','u2','u3'}


def test_prune_honors_cancel_before_processing(tmp_path):
    album = tmp_path / "Album"
    album.mkdir()
    (album / "IMG.JPG").write_bytes(b"x")
    engine.request_cancel()
    try:
        with pytest.raises(engine.Cancelled):
            engine.prune(str(tmp_path), {"Album":"uuid"}, {"albums":{"uuid":"Album"}}, set(), [str(album)])
    finally:
        engine.CANCEL.clear()
