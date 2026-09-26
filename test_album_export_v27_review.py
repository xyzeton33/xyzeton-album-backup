"""公開直前レビューのリグレッションテスト（実機不要）

ChatGPTによる七次レビューの指摘。v2.8.0 ですべて修正済み。
・ハードリンク検査が利用者の既存ファイルを消しうる問題（最重要）
・_album_state.json.tmp を予約名に追加
・親フォルダ名を「フォルダ自身のUUID順」で確定
・0件になった時に古いレポートを残さない

実行:
    python -m pytest -q test_album_export_v27_release_review.py

現行 v2.7.0 では、以下の境界ケースを確認するためのテストです。
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import album_export as engine


def _make_parent_collision_db(path: Path, child_uuids: tuple[str, str]):
    con = sqlite3.connect(path)
    c = con.cursor()
    c.executescript("""
    CREATE TABLE ZASSET(
        Z_PK INTEGER PRIMARY KEY,
        ZDIRECTORY TEXT,
        ZFILENAME TEXT,
        ZTRASHEDSTATE INTEGER DEFAULT 0
    );
    CREATE TABLE ZGENERICALBUM(
        Z_PK INTEGER PRIMARY KEY,
        ZTITLE TEXT,
        ZKIND INTEGER,
        ZTRASHEDSTATE INTEGER DEFAULT 0,
        ZPARENTFOLDER INTEGER,
        ZUUID TEXT
    );
    CREATE TABLE Z_1ASSETS(
        Z_1ALBUMS INTEGER,
        Z_3ASSETS INTEGER
    );
    """)
    c.executemany("INSERT INTO ZGENERICALBUM VALUES(?,?,?,?,?,?)", [
        (1, None, 3999, 0, None, "root"),
        (10, "A:B", 4000, 0, 1, "folder-111111"),
        (11, "A?B", 4000, 0, 1, "folder-222222"),
        (20, "One", 2, 0, 10, child_uuids[0]),
        (21, "Two", 2, 0, 11, child_uuids[1]),
    ])
    pk = 100
    for alb in (20, 21):
        for _ in range(3):  # find_join_table() needs >= 3 rows
            c.execute("INSERT INTO ZASSET VALUES(?,?,?,?)",
                      (pk, "DCIM/100A", f"{pk}.JPG", 0))
            c.execute("INSERT INTO Z_1ASSETS VALUES(?,?)", (alb, pk))
            pk += 1
    con.commit()
    con.close()


def _roots_by_leaf(albums):
    result = {}
    for p in albums:
        parts = os.path.normpath(p).split(os.sep)
        result[parts[-1]] = parts[0]
    return result


def test_colliding_parent_folder_name_is_stable_when_child_album_order_changes(tmp_path, monkeypatch):
    """親フォルダの素名/サフィックス名は、子アルバムUUIDの並びに左右されないこと。"""
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))
    db1 = tmp_path / "p1.sqlite"
    db2 = tmp_path / "p2.sqlite"
    _make_parent_collision_db(db1, ("aaa", "zzz"))
    _make_parent_collision_db(db2, ("zzz", "aaa"))

    a1, *_ = engine.parse_albums(str(db1))
    a2, *_ = engine.parse_albums(str(db2))

    assert _roots_by_leaf(a1) == _roots_by_leaf(a2)


def test_state_temp_name_is_reserved(tmp_path, monkeypatch):
    """_album_state.json.tmp も内部一時ファイル名なので、ユーザーアルバムと衝突させない。"""
    assert os.path.normcase(engine.STATE_FILE + ".tmp").casefold() in engine.internal_names()


def test_hardlink_probe_does_not_delete_preexisting_user_file(tmp_path):
    """ハードリンク検査は、出力先に同名の既存ファイルがあっても削除してはいけない。"""
    cache = tmp_path / "cache"
    out = tmp_path / "out"
    cache.mkdir()
    out.mkdir()

    marker = out / ".hardlink_test_link"
    marker.write_bytes(b"USER-DATA")

    engine.check_hardlink(str(cache), str(out))

    assert marker.exists()
    assert marker.read_bytes() == b"USER-DATA"


def test_no_cloud_only_result_removes_stale_report(tmp_path):
    """今回 cloud-only が0件なら、前回の一覧を現在の結果として残さない。"""
    engine.set_language("ja")
    old = tmp_path / "_iCloudにしか無い写真.txt"
    old.write_text("old result", encoding="utf-8")

    n = engine.report_cloud_only(
        str(tmp_path),
        {},
        {"DCIM/100APPLE/A.JPG"},
        [("DCIM/100APPLE/A.JPG", 1)],
    )

    assert n == 0
    assert not old.exists()


def test_parent_folder_names_survive_adding_an_album(tmp_path, monkeypatch):
    """アルバムを1つ増やしただけで親フォルダ名が入れ替わってはいけない"""
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))

    def build(name, with_extra):
        db = tmp_path / name
        con = sqlite3.connect(db)
        c = con.cursor()
        c.executescript("""CREATE TABLE ZASSET(Z_PK INTEGER PRIMARY KEY,ZDIRECTORY TEXT,ZFILENAME TEXT,ZTRASHEDSTATE INTEGER DEFAULT 0);
        CREATE TABLE ZGENERICALBUM(Z_PK INTEGER PRIMARY KEY,ZTITLE TEXT,ZKIND INTEGER,ZTRASHEDSTATE INTEGER DEFAULT 0,ZPARENTFOLDER INTEGER,ZUUID TEXT);
        CREATE TABLE Z_1ASSETS(Z_1ALBUMS INTEGER,Z_3ASSETS INTEGER);""")
        rows = [(1, None, 3999, 0, None, "root"), (10, "A:B", 4000, 0, 1, "folder-111"),
                (11, "A?B", 4000, 0, 1, "folder-222"), (20, "One", 2, 0, 10, "zzz"),
                (21, "Two", 2, 0, 11, "aaa")]
        albums = [20, 21]
        if with_extra:
            rows.append((22, "Extra", 2, 0, 10, "000"))
            albums.append(22)
        for r in rows:
            c.execute("INSERT INTO ZGENERICALBUM VALUES(?,?,?,?,?,?)", r)
        pk = 100
        for alb in albums:
            for _ in range(3):
                c.execute("INSERT INTO ZASSET VALUES(?,?,?,?)", (pk, "DCIM/100A", f"{pk}.JPG", 0))
                c.execute("INSERT INTO Z_1ASSETS VALUES(?,?)", (alb, pk))
                pk += 1
        con.commit()
        con.close()
        return str(db)

    def roots(albums):
        return {p.split(os.sep)[-1]: p.split(os.sep)[0] for p in albums}

    before, *_ = engine.parse_albums(build("before.sqlite", False))
    after, *_ = engine.parse_albums(build("after.sqlite", True))
    assert roots(before)["One"] == roots(after)["One"]
    assert roots(before)["Two"] == roots(after)["Two"]


# ---- v2.8.1: 一時的なローカルI/Oロック（ウイルス対策など）への耐性
import asyncio as _asyncio
import builtins as _builtins
import errno as _errno


class _TinyAFC:
    def __init__(self, data=b"x" * 100):
        self.d = data
        self.pos = 0
        self.opens = 0
    async def stat(self, p): return {"st_size": len(self.d)}
    async def fopen(self, p, m):
        self.opens += 1; self.pos = 0; return 1
    async def fseek(self, h, o, w=0): self.pos = o
    async def fread(self, h, n):
        d = self.d[self.pos:self.pos + n]; self.pos += len(d); return d
    async def fclose(self, h): pass


def _no_sleep(monkeypatch, counter=None):
    """待ち時間を潰す。元の sleep を保持してから差し替えないと無限再帰になる。"""
    real_sleep = _asyncio.sleep
    async def fast(_):
        if counter is not None:
            counter["sleep"] += 1
        await real_sleep(0)
    monkeypatch.setattr(engine.asyncio, "sleep", fast)


def _patch_open(monkeypatch, err, fail_times=None):
    real = _builtins.open
    state = {"n": 0}
    def fake(p, m="r", *a, **k):
        if str(p).endswith(".part") and ("w" in m or "a" in m):
            state["n"] += 1
            if fail_times is None or state["n"] <= fail_times:
                raise err
        return real(p, m, *a, **k)
    monkeypatch.setattr(_builtins, "open", fake)


def test_transient_permission_error_is_retried(tmp_path, monkeypatch):
    """ウイルス対策等による一時的なEACCESは待って再試行し、完走すること。
    ここで即座に諦めると、8万件のバックアップが毎回途中で止まる。"""
    _no_sleep(monkeypatch)
    _patch_open(monkeypatch, PermissionError(_errno.EACCES, "Permission denied"), fail_times=3)
    afc = _TinyAFC()
    dst = tmp_path / "IMG.PNG"
    ok = _asyncio.run(engine.download(afc, "DCIM/IMG.PNG", str(dst), 100))
    assert ok and dst.read_bytes() == afc.d
    assert afc.opens == 1          # iPhoneから取り直していない


def test_persistent_permission_error_explains_the_fix(tmp_path, monkeypatch):
    """何度待っても駄目な場合は止めるが、対処法を必ず示すこと"""
    _no_sleep(monkeypatch)
    _patch_open(monkeypatch, PermissionError(_errno.EACCES, "Permission denied"))
    with pytest.raises(engine.LocalIOError) as ei:
        _asyncio.run(engine.download(_TinyAFC(), "DCIM/IMG.PNG", str(tmp_path / "IMG.PNG"), 100))
    msg = str(ei.value)
    assert "除外" in msg and "続きから再開" in msg


def test_disk_full_is_not_retried(tmp_path, monkeypatch):
    """容量不足は待っても直らないので、再試行せず即座に止めること"""
    calls = {"sleep": 0}
    _no_sleep(monkeypatch, calls)
    _patch_open(monkeypatch, OSError(_errno.ENOSPC, "No space left"))
    with pytest.raises(engine.LocalIOError) as ei:
        _asyncio.run(engine.download(_TinyAFC(), "DCIM/IMG.PNG", str(tmp_path / "IMG.PNG"), 100))
    assert ei.value.errno == _errno.ENOSPC
    assert calls["sleep"] == 0


def test_device_handle_is_not_held_while_waiting_on_local_lock(tmp_path, monkeypatch):
    """PC側のロック待ちの間、iPhone側のファイルを開いたままにしない。
    保持したまま最大15秒待つと、長時間のバックアップで接続が不安定になる。"""
    _no_sleep(monkeypatch)

    class CountingAFC(_TinyAFC):
        def __init__(self):
            super().__init__()
            self.open_now = 0
            self.max_open = 0
        async def fopen(self, p, m):
            self.open_now += 1
            self.max_open = max(self.max_open, self.open_now)
            return await super().fopen(p, m)
        async def fclose(self, h):
            self.open_now -= 1

    _patch_open(monkeypatch, PermissionError(_errno.EACCES, "locked"), fail_times=4)
    afc = CountingAFC()
    ok = _asyncio.run(engine.download(afc, "DCIM/IMG.PNG", str(tmp_path / "IMG.PNG"), 100))
    assert ok
    assert afc.opens == 1          # ロック待ち中に開いていない
    assert afc.open_now == 0       # 開きっぱなしが残らない


def test_destination_loss_waits_instead_of_failing_every_file(tmp_path, monkeypatch):
    """保存先ドライブが転送中に消えたら、復帰を待って続きから再開する。
    実機で外付けHDDが9分間切断され、待たずに1件ずつ失敗を積んだ結果
    9,997件が『取得できず』になった事例の再発防止。"""
    import builtins as _b

    cache = tmp_path / "cache"
    out = tmp_path / "out"
    cache.mkdir()
    out.mkdir()
    data = {f"DCIM/100A/f{i:03d}.PNG": bytes([i % 251]) * 200 for i in range(12)}

    class FS_AFC:
        def __init__(self):
            self.cur = None
            self.pos = 0
        async def listdir(self, p):
            return sorted({k[len(p) + 1:].split("/")[0] for k in data if k.startswith(p + "/")})
        async def stat(self, p):
            if p in data:
                return {"st_ifmt": "S_IFREG", "st_size": len(data[p])}
            return {"st_ifmt": "S_IFDIR", "st_size": 0}
        async def exists(self, p): return True
        async def fopen(self, p, m):
            self.cur = p; self.pos = 0; return 1
        async def fseek(self, h, o, w=0): self.pos = o
        async def fread(self, h, n):
            d = data[self.cur][self.pos:self.pos + n]; self.pos += len(d); return d
        async def fclose(self, h): pass

    _no_sleep(monkeypatch)
    engine._wait_for_destination.__defaults__ = (60, 1)   # 待機間隔を詰める

    afc = FS_AFC()
    files = _asyncio.run(engine.scan_dcim(afc))

    state = {"n": 0, "gone": False, "checks": 0}
    real_open = _b.open
    real_isdir = os.path.isdir

    def guard(p, m="r", *a, **k):
        if state["gone"] and str(p).startswith(str(cache)):
            raise FileNotFoundError(3, "path not found")
        return real_open(p, m, *a, **k)

    def isdir(p):
        # 消えている間の問い合わせを数え、2回目でドライブが戻ったことにする
        if state["gone"] and os.path.normpath(p) == os.path.normpath(str(cache)):
            state["checks"] += 1
            if state["checks"] >= 2:
                state["gone"] = False
                monkeypatch.setattr(_b, "open", real_open)
                return True
            return False
        return real_isdir(p)

    monkeypatch.setattr(engine.os.path, "isdir", isdir)
    original_download = engine.download

    async def hooked(a, remote, local, size, retries=3):
        state["n"] += 1
        if state["n"] == 5 and not state["gone"] and state["checks"] == 0:
            state["gone"] = True          # 5件目でドライブが消える
            monkeypatch.setattr(_b, "open", guard)
        return await original_download(a, remote, local, size, retries)

    monkeypatch.setattr(engine, "download", hooked)
    try:
        failed = _asyncio.run(engine.pull_dcim(afc, str(cache), files, str(out)))
    finally:
        engine._wait_for_destination.__defaults__ = (1800, 5)

    assert failed == 0                    # 1件も「取得できず」にしない
    got = sum(1 for _, _, fs in os.walk(cache) for f in fs if not f.endswith((".part", ".size")))
    assert got == len(data)               # 最終的に全件そろう


# ---- v3.1.0: 中間テーブル検出の厳格化（レビュー指摘）
def _join_db(path, variant):
    con = sqlite3.connect(path)
    c = con.cursor()
    c.executescript("""CREATE TABLE ZASSET(Z_PK INTEGER PRIMARY KEY,ZDIRECTORY TEXT,ZFILENAME TEXT,ZTRASHEDSTATE INTEGER DEFAULT 0);
    CREATE TABLE ZGENERICALBUM(Z_PK INTEGER PRIMARY KEY,ZTITLE TEXT,ZKIND INTEGER,ZTRASHEDSTATE INTEGER DEFAULT 0,ZPARENTFOLDER INTEGER,ZUUID TEXT);
    CREATE TABLE Z_28ASSETS(Z_28ALBUMS INTEGER,Z_3ASSETS INTEGER);""")
    c.execute("INSERT INTO ZGENERICALBUM VALUES(1,NULL,3999,0,NULL,'root')")
    c.execute("INSERT INTO ZGENERICALBUM VALUES(12,'Trip',2,0,1,'u1')")
    c.executemany("INSERT INTO ZASSET VALUES(?,?,?,?)",
                  [(100 + i, "DCIM/100A", f"a{i}.JPG", 0) for i in range(10)])
    c.executemany("INSERT INTO Z_28ASSETS VALUES(?,?)", [(12, 100 + i) for i in range(10)])
    if variant == "decoy":
        # 無関係だが両列の整数がPK集合に含まれ、行数はこちらが多い統計表
        c.execute("CREATE TABLE ZDECOYSTATS(ZA INTEGER, ZB INTEGER)")
        c.executemany("INSERT INTO ZDECOYSTATS VALUES(?,?)",
                      [(12, 100 + (i % 10)) for i in range(500)])
    if variant == "renamed":
        c.execute("DROP TABLE Z_28ASSETS")
        c.execute("CREATE TABLE Z_9MEMBERS(Z_9CONT INTEGER, Z_4ITEMS INTEGER)")
        c.executemany("INSERT INTO Z_9MEMBERS VALUES(?,?)", [(12, 100 + i) for i in range(10)])
    con.commit()
    con.close()


def _detect(path):
    con = sqlite3.connect(path)
    cur = con.cursor()
    cols = lambda t: [r[1] for r in cur.execute(f'PRAGMA table_info("{t}")').fetchall()]
    try:
        got = engine.find_join_table(cur, cols)
    finally:
        con.close()
    return got[0] if got else None


def test_join_table_detection_ignores_high_row_decoy(tmp_path):
    """行数が多いだけの無関係な表を採用してはいけない。
    採用するとアルバムの中身が丸ごと誤る。"""
    db = tmp_path / "decoy.sqlite"
    _join_db(db, "decoy")
    assert _detect(str(db)) == "Z_28ASSETS"


def test_join_table_detection_survives_renamed_columns(tmp_path):
    """名前への依存を減らした検出であること（iOS版差への耐性）"""
    db = tmp_path / "renamed.sqlite"
    _join_db(db, "renamed")
    assert _detect(str(db)) == "Z_9MEMBERS"


def test_join_table_detection_is_still_correct_on_plain_db(tmp_path):
    db = tmp_path / "ok.sqlite"
    _join_db(db, "ok")
    assert _detect(str(db)) == "Z_28ASSETS"
