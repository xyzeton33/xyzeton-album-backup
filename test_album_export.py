"""iPhone Album Backup: 実機不要のリグレッションテスト

    python -m pytest -q test_album_export.py

初出はChatGPTによるコードレビュー。指摘された8件はすべて実在するバグで、
v1.5.0 で修正済み。今後の変更で再発していないかを確認するために残しています。
"""
from __future__ import annotations
import argparse, asyncio, builtins, errno, importlib.util, os, sys, types
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import album_export as engine


@pytest.fixture(autouse=True)
def reset_engine_globals():
    engine.CANCEL.clear()
    old_log = engine.log
    old_handler = engine._event_handler
    engine.set_logger(lambda *args, **kwargs: None)
    engine.set_event_handler(None)
    yield
    engine.CANCEL.clear()
    engine.set_logger(old_log)
    engine.set_event_handler(old_handler)


class BytesAFC:
    def __init__(self, payload: bytes, *, fail_read_call=None, close_error=None, alive=True):
        self.payload = payload; self.fail_read_call = fail_read_call
        self.close_error = close_error; self.alive = alive
        self.offset = 0; self.read_calls = 0; self.open_calls = 0
        self.close_calls = 0; self.seek_calls = []
    async def fopen(self, remote, mode="r"):
        self.open_calls += 1; self.offset = 0; return 1
    async def fseek(self, handle, offset, whence=os.SEEK_SET):
        assert whence == os.SEEK_SET
        self.offset = offset; self.seek_calls.append(offset)
    async def fread(self, handle, size):
        self.read_calls += 1
        if self.fail_read_call == self.read_calls:
            self.alive = False; raise ConnectionError("simulated USB disconnect")
        chunk = self.payload[self.offset:self.offset + size]; self.offset += len(chunk); return chunk
    async def fclose(self, handle):
        self.close_calls += 1
        if self.close_error is not None: raise self.close_error
    async def exists(self, path): return self.alive


class BigTreeAFC:
    def __init__(self, dirs=84, files_per_dir=1000, file_size=1024):
        self.dirs = dirs; self.files_per_dir = files_per_dir; self.file_size = file_size
        self.stat_calls = 0; self.listdir_calls = 0
    async def listdir(self, path):
        self.listdir_calls += 1
        if path == "DCIM": return [f"{100+i}APPLE" for i in range(self.dirs)]
        return [f"IMG_{j:04d}.JPG" for j in range(self.files_per_dir)]
    async def stat(self, path):
        self.stat_calls += 1
        if path.count("/") == 1: return {"st_ifmt": "S_IFDIR", "st_size": 0}
        return {"st_ifmt": "S_IFREG", "st_size": self.file_size}


class FakeLockdown:
    def __init__(self):
        self.display_name = "Fake iPhone"; self.product_version = "0"; self.closed = False
    async def close(self): self.closed = True


class TrackingAfcCM:
    def __init__(self, lockdown=None):
        self.lockdown = lockdown; self.entered = False; self.exited = False; self.afc = BytesAFC(b"")
    async def __aenter__(self): self.entered = True; return self.afc
    async def __aexit__(self, exc_type, exc, tb): self.exited = True


def run(coro): return asyncio.run(coro)

def make_args(tmp_path, **overrides):
    values = dict(out=str(tmp_path), cache=None, list=False, skip_pull=True, refresh_db=False,
                  db="dummy.sqlite", no_date_prefix=False, media_types=[], lang="ja", prune=False, gui=False)
    values.update(overrides); return argparse.Namespace(**values)


def test_download_success_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "CHUNK", 3)
    dst = tmp_path / "DCIM" / "100APPLE" / "IMG_0001.JPG"
    afc = BytesAFC(b"abcdef")
    changed = run(engine.download(afc, "DCIM/100APPLE/IMG_0001.JPG", str(dst), 6))
    assert changed is True
    assert dst.read_bytes() == b"abcdef"
    assert not Path(str(dst) + ".part").exists()

def test_download_skips_existing_same_size_without_opening_remote(tmp_path):
    dst = tmp_path / "IMG.JPG"; dst.write_bytes(b"abcdef")
    afc = BytesAFC(b"XXXXXX")
    changed = run(engine.download(afc, "DCIM/IMG.JPG", str(dst), 6))
    assert changed is False
    assert afc.open_calls == 0
    assert dst.read_bytes() == b"abcdef"

def test_wait_reconnect_honors_cancel_before_attempting_reconnect():
    calls = 0
    async def reconnect():
        nonlocal calls; calls += 1; return BytesAFC(b"")
    engine.request_cancel()
    with pytest.raises(engine.Cancelled):
        run(engine._wait_reconnect(reconnect, timeout=1, interval=1))
    assert calls == 0

def test_place_uses_hardlink_when_supported(tmp_path):
    src = tmp_path / "cache" / "IMG.JPG"; src.parent.mkdir(); src.write_bytes(b"abc")
    out = tmp_path / "album"
    placed = Path(engine.place(str(src), str(out), "100APPLE"))
    assert placed.exists(); assert os.path.samefile(src, placed)

def test_prune_does_not_move_paths_recorded_as_placed(tmp_path):
    album = tmp_path / "Album"; album.mkdir()
    current = album / "IMG.JPG"; current.write_bytes(b"abc")
    dropped = engine.prune(str(tmp_path), {"Album": "uuid1"}, {"albums": {"uuid1": "Album"}},
                           {str(current)}, [str(album)])
    assert dropped == []; assert current.exists()

def test_scan_remote_84000_files_counts_afc_round_trips():
    afc = BigTreeAFC(dirs=84, files_per_dir=1000)
    files = run(engine.scan_remote(afc, "DCIM"))
    assert len(files) == 84_000
    assert afc.stat_calls == 84_084
    assert afc.listdir_calls == 85

# ---- 指摘されたバグ群 ----
def test_download_preserves_partial_file_for_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "CHUNK", 3)
    dst = tmp_path / "IMG.JPG"
    afc = BytesAFC(b"abcdef", fail_read_call=2)
    with pytest.raises(ConnectionError):
        run(engine.download(afc, "DCIM/IMG.JPG", str(dst), 6, retries=1))
    assert Path(str(dst) + ".part").read_bytes() == b"abc"

def test_download_close_error_does_not_mask_cancel(tmp_path):
    dst = tmp_path / "IMG.JPG"
    afc = BytesAFC(b"abcdef", close_error=ConnectionError("socket already gone"))
    engine.request_cancel()
    with pytest.raises(engine.Cancelled):
        run(engine.download(afc, "DCIM/IMG.JPG", str(dst), 6, retries=1))

def test_run_does_not_erase_cancel_requested_just_before_coroutine_starts(tmp_path, monkeypatch):
    def fake_parse(_):
        engine._check_cancel(); return {}, set(), {}, {}, {}, {}
    monkeypatch.setattr(engine, "parse_albums", fake_parse)
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))
    engine.request_cancel()
    with pytest.raises(engine.Cancelled):
        run(engine.run(make_args(tmp_path, list=True)))

def test_cancel_requested_during_organization_stops_before_next_asset(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))
    monkeypatch.setattr(engine, "parse_albums", lambda _: ({"Album": ["DCIM/A.JPG", "DCIM/B.JPG"]},
                   {"DCIM/A.JPG", "DCIM/B.JPG"}, {}, {"Album": "uuid"}, {}, {}))
    calls = 0
    def fake_place_asset(*args, **kwargs):
        nonlocal calls; calls += 1
        if calls == 1: engine.request_cancel()
        return True
    monkeypatch.setattr(engine, "place_asset", fake_place_asset)
    with pytest.raises(engine.Cancelled):
        run(engine.run(make_args(tmp_path)))
    assert calls == 1

def test_move_merge_preserves_both_files_on_name_collision(tmp_path):
    src = tmp_path / "src"; dst = tmp_path / "dst"; src.mkdir(); dst.mkdir()
    (src / "IMG.JPG").write_bytes(b"SOURCE"); (dst / "IMG.JPG").write_bytes(b"DESTINATION")
    engine._move_merge(str(src), str(dst))
    payloads = sorted(p.read_bytes() for p in dst.rglob("*") if p.is_file())
    assert payloads == [b"DESTINATION", b"SOURCE"]

def test_place_does_not_silently_reuse_wrong_tagged_collision(tmp_path):
    src = tmp_path / "cache" / "100APPLE" / "IMG.JPG"; src.parent.mkdir(parents=True); src.write_bytes(b"SOURCE")
    dst = tmp_path / "Album"; dst.mkdir()
    (dst / "IMG.JPG").write_bytes(b"OTHER-1"); (dst / "IMG_100APPLE.JPG").write_bytes(b"OTHER-2")
    placed = Path(engine.place(str(src), str(dst), "100APPLE"))
    assert placed.read_bytes() == b"SOURCE"

def test_disk_full_is_fatal_without_three_remote_retries(tmp_path, monkeypatch):
    dst = tmp_path / "IMG.JPG"; afc = BytesAFC(b"abcdef")
    real_open = builtins.open
    def fake_open(path, mode="r", *args, **kwargs):
        if str(path).endswith(".part") and "w" in mode:
            raise OSError(errno.ENOSPC, "simulated disk full")
        return real_open(path, mode, *args, **kwargs)
    async def no_sleep(_): return None
    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(engine.asyncio, "sleep", no_sleep)
    with pytest.raises(OSError) as exc:
        run(engine.download(afc, "DCIM/IMG.JPG", str(dst), 6, retries=3))
    assert exc.value.errno == errno.ENOSPC
    # v2.9.1: PC側のファイルを先に開くようにしたので、書き込めない時点で
    # iPhone側は一度も開かない（無駄な端末アクセスが減り、接続も安定する）
    assert afc.open_calls == 0

def test_run_closes_device_resources_when_parse_raises(tmp_path, monkeypatch):
    lockdown = FakeLockdown(); cm = TrackingAfcCM(lockdown)
    async def fake_connect(): return lockdown
    async def fake_pull_db(afc, dbdir, refresh=False): return "dummy.sqlite"
    monkeypatch.setattr(engine, "connect", fake_connect)
    monkeypatch.setattr(engine, "AfcService", lambda lockdown=None: cm)
    monkeypatch.setattr(engine, "pull_photos_db", fake_pull_db)
    monkeypatch.setattr(engine, "parse_albums", lambda _: (_ for _ in ()).throw(RuntimeError("bad db")))
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))
    with pytest.raises(RuntimeError, match="bad db"):
        run(engine.run(make_args(tmp_path, db=None, list=True)))
    assert cm.exited is True
    assert lockdown.closed is True
