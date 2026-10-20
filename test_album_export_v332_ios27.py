"""iOS 27 の Photos.sqlite で解析が止まった件のリグレッションテスト（実機不要）

2026-10-20、iOS 27.0.1（iPhone 11 Pro Max）で [2/4] アルバムの解析中に
    sqlite3.OperationalError: unrecognized option: "contentless_delete"
で止まった。Photos.sqlite に、配布版に同梱した SQLite が知らないオプション付きの
仮想表（FTS5）があり、結合表を探す処理が PRAGMA table_info でその表を開いたため。

ここでは「手元の SQLite が解釈できない仮想表」を2通りで作り、
・解析が止まらないこと
・アルバムが正しく取れること（仮想表を結合表と誤認しないこと）
・診断用のスキーマ書き出しも止まらないこと
を確かめる。どちらの作り方も、FTS5 の有無に関係なく skip せずに実行される。

実行例:
    python -m pytest -q test_album_export_v332_ios27.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import album_export as engine

ALBUMS = ["家族", "旅行", "猫"]


def _base_db(path: Path):
    con = sqlite3.connect(path)
    c = con.cursor()
    c.execute("CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZKIND INTEGER, ZPARENTFOLDER INTEGER, ZUUID TEXT)")
    c.execute("CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZDIRECTORY TEXT, ZFILENAME TEXT)")
    c.execute("CREATE TABLE Z_1ASSETS (Z_1ALBUMS INTEGER, Z_3ASSETS INTEGER)")
    for i, name in enumerate(ALBUMS, 1):
        c.execute("INSERT INTO ZGENERICALBUM VALUES (?,?,?,?,?)", (i, name, 2, None, f"uuid{i}"))
        c.execute("INSERT INTO ZASSET VALUES (?,?,?)", (100 + i, "DCIM/100APPLE", f"{i}.JPG"))
        c.execute("INSERT INTO Z_1ASSETS VALUES (?,?)", (i, 100 + i))
    con.commit()
    return con


def _add_unknown_module_vtab(con):
    """どの SQLite でも開けない仮想表（存在しないモジュール）を、スキーマに直接書き込む。"""
    c = con.cursor()
    c.execute("PRAGMA writable_schema=ON")
    c.execute("INSERT INTO sqlite_master(type, name, tbl_name, rootpage, sql) VALUES "
              "('table', 'ZFUTURESEARCH', 'ZFUTURESEARCH', 0, "
              "'CREATE VIRTUAL TABLE ZFUTURESEARCH USING zz_future_module(a, b)')")
    c.execute("PRAGMA writable_schema=OFF")
    con.commit()


def _add_fts5_with_unknown_option(con):
    """iOS 27 と同じ形: FTS5 の表で、手元の SQLite が知らないオプションを持つもの。
    FTS5 が無い SQLite では作れないので、そのときは存在しないモジュールの表で代える。"""
    c = con.cursor()
    try:
        c.execute("CREATE VIRTUAL TABLE ZSEARCHFTS USING fts5(a, b, content='')")
        c.execute("INSERT INTO ZSEARCHFTS(rowid, a, b) VALUES (1, 'x', 'y')")
        con.commit()
    except sqlite3.OperationalError:
        _add_unknown_module_vtab(con)
        return "unknown-module"
    c.execute("PRAGMA writable_schema=ON")
    c.execute("UPDATE sqlite_master SET sql = replace(sql, 'content=''''', "
              "'content='''', zz_future_option=1') WHERE name='ZSEARCHFTS'")
    c.execute("PRAGMA writable_schema=OFF")
    con.commit()
    return "fts5"


def _broken_db(tmp_path, add):
    db = tmp_path / "Photos.sqlite"
    con = _base_db(db)
    add(con)
    con.close()
    return db


@pytest.mark.parametrize("add", [_add_unknown_module_vtab, _add_fts5_with_unknown_option],
                         ids=["unknown-module", "fts5-unknown-option"])
def test_precondition_old_code_path_fails(tmp_path, add):
    """前提の確認: この DB では、仮想表の列名を調べると実際にエラーになる。"""
    db = _broken_db(tmp_path, add)
    con = sqlite3.connect(db)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        vt = [n for n in names if n in ("ZFUTURESEARCH", "ZSEARCHFTS")]
        assert vt, "仮想表が作られていない"
        with pytest.raises(sqlite3.OperationalError):
            con.execute(f"PRAGMA table_info({engine._qi(vt[0])})").fetchall()
    finally:
        con.close()


@pytest.mark.parametrize("add", [_add_unknown_module_vtab, _add_fts5_with_unknown_option],
                         ids=["unknown-module", "fts5-unknown-option"])
def test_parse_albums_skips_unreadable_virtual_tables(tmp_path, monkeypatch, add):
    db = _broken_db(tmp_path, add)
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))

    albums, all_files, *_ = engine.parse_albums(str(db))

    assert sorted(albums) == sorted(ALBUMS)
    for i, name in enumerate(ALBUMS, 1):
        assert [os.path.basename(p) for p in albums[name]] == [f"{i}.JPG"]
    assert not (tmp_path / "schema_dump.txt").exists(), "正常に解析できたのに診断ファイルが作られた"


def test_dump_schema_does_not_stop_on_virtual_tables(tmp_path):
    db = _broken_db(tmp_path, _add_unknown_module_vtab)
    con = sqlite3.connect(db)
    try:
        out = tmp_path / "schema_dump.txt"
        engine.dump_schema(con.cursor(), str(out))
    finally:
        con.close()
    text = out.read_text(encoding="utf-8")
    assert "ZFUTURESEARCH (virtual)" in text
    assert "Z_1ASSETS" in text and "ZASSET" in text and "ZGENERICALBUM" in text


def test_plain_tables_excludes_only_virtual_tables(tmp_path):
    db = _broken_db(tmp_path, _add_unknown_module_vtab)
    con = sqlite3.connect(db)
    try:
        names = engine._plain_tables(con.cursor())
    finally:
        con.close()
    assert "ZFUTURESEARCH" not in names
    assert {"ZASSET", "ZGENERICALBUM", "Z_1ASSETS"} <= set(names)


def test_real_contentless_delete_table_when_supported(tmp_path, monkeypatch):
    """手元の SQLite が contentless_delete を知っている場合（3.43.0 以降・FTS5 あり）は、
    その表があっても解析が通ること。知らない場合は、上のテストと同じく読み飛ばされること。"""
    db = tmp_path / "Photos.sqlite"
    con = _base_db(db)
    try:
        con.execute("CREATE VIRTUAL TABLE ZSEARCHFTS USING fts5(a, content='', contentless_delete=1)")
        con.commit()
        made = True
    except sqlite3.OperationalError:
        _add_unknown_module_vtab(con)
        made = False
    con.close()
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))
    albums, *_ = engine.parse_albums(str(db))
    assert sorted(albums) == sorted(ALBUMS), f"contentless_delete table created: {made}"


# ---------------------------------------------------------------------------
# 仮想表に付属する内部表（shadow table）も候補から外す（ChatGPTレビューの指摘）
#
# FTS5 の表を作ると ZXXX_config / _data / _docsize / _idx が自動で作られる。
# これらは検索用のデータで、アルバム⇔写真の対応表ではない。v3.3.2 の最初の修正では
# 仮想表本体だけを外していたため、結合表を探す処理がこれらを全件 SELECT していた。
# FTS5 が無い SQLite でも skip しないよう、そのときは「存在しないモジュールの仮想表」と
# 同じ名前の付け方の通常表で代える（build.bat は skip が1件でもあると止まるため）。

SHADOW_SUFFIXES = ("_config", "_data", "_docsize", "_idx")


def _db_with_shadow_tables(path: Path):
    """仮想表と、その付属表がある DB。戻り値: (仮想表の名前, 付属表の名前の集合)"""
    con = _base_db(path)
    c = con.cursor()
    try:
        c.execute("CREATE VIRTUAL TABLE ZSEARCHFTS USING fts5(a, content='')")
        for i in range(10):
            c.execute("INSERT INTO ZSEARCHFTS(rowid, a) VALUES (?, ?)", (i + 1, "apple photo"))
        vt = "ZSEARCHFTS"
    except sqlite3.OperationalError:
        _add_unknown_module_vtab(con)
        vt = "ZFUTURESEARCH"
        for s in SHADOW_SUFFIXES:
            c.execute(f"CREATE TABLE {vt}{s} (id INTEGER, v INTEGER)")
            # 中身は「アルバムPK, 写真PK」に見える整数にして、誤認しやすい形にしておく
            c.executemany(f"INSERT INTO {vt}{s} VALUES (?, ?)", [(i, 100 + i) for i in (1, 2, 3)])
    con.commit()
    con.close()
    return vt, {vt + s for s in SHADOW_SUFFIXES}


def test_shadow_tables_are_not_join_candidates(tmp_path):
    db = tmp_path / "Photos.sqlite"
    _vt, shadows = _db_with_shadow_tables(db)
    con = sqlite3.connect(db)
    try:
        names = set(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        assert shadows <= names, "付属表が作られていない"
        candidates = set(engine._plain_tables(con.cursor()))
    finally:
        con.close()
    assert not (shadows & candidates), f"付属表が候補に残っている: {sorted(shadows & candidates)}"
    assert {"ZASSET", "ZGENERICALBUM", "Z_1ASSETS"} <= candidates
    assert not any(n.casefold().startswith("sqlite_") for n in candidates)


def test_find_join_table_never_reads_shadow_tables(tmp_path, monkeypatch):
    """実際に実行された SQL を記録し、付属表を一度も読んでいないことを確かめる。"""
    db = tmp_path / "Photos.sqlite"
    _vt, shadows = _db_with_shadow_tables(db)
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))

    executed = []
    real_connect = sqlite3.connect

    def tracing_connect(*a, **k):
        con = real_connect(*a, **k)
        con.set_trace_callback(executed.append)
        return con

    monkeypatch.setattr(engine.sqlite3, "connect", tracing_connect)
    albums, *_ = engine.parse_albums(str(db))

    assert sorted(albums) == sorted(ALBUMS)
    # このツールは表名を必ず "..." で囲んで SQL に入れる（_qi）。
    # FTS5 自身が内部で発行する SQL（'main'.'ZSEARCHFTS_config' のような形）は数えない。
    touched = [sql for sql in executed for s in shadows if f'"{s}"' in sql]
    assert not touched, f"付属表を読んだ SQL: {touched[:3]}"


class _CursorWithoutTableList:
    """PRAGMA table_list を知らない古い SQLite（3.36 以前）のふり。知らない PRAGMA は0行を返す。"""
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, *a):
        if "table_list" in sql:
            return self._cur.execute("SELECT 1 WHERE 0")
        return self._cur.execute(sql, *a)


def test_shadow_tables_excluded_without_table_list(tmp_path):
    db = tmp_path / "Photos.sqlite"
    _vt, shadows = _db_with_shadow_tables(db)
    con = sqlite3.connect(db)
    try:
        candidates = set(engine._plain_tables(_CursorWithoutTableList(con.cursor())))
    finally:
        con.close()
    assert not (shadows & candidates)
    assert {"ZASSET", "ZGENERICALBUM", "Z_1ASSETS"} <= candidates


def test_similar_names_that_are_not_shadow_tables_are_kept(tmp_path):
    """仮想表と名前が似ているだけの通常表（名前＋"_" で始まらないもの）は外さない。"""
    db = tmp_path / "Photos.sqlite"
    con = _base_db(db)
    _add_unknown_module_vtab(con)            # ZFUTURESEARCH
    con.execute("CREATE TABLE ZFUTURESEARCHES (a INTEGER, b INTEGER)")
    con.commit()
    con.close()
    con = sqlite3.connect(db)
    try:
        candidates = set(engine._plain_tables(con.cursor()))
    finally:
        con.close()
    assert "ZFUTURESEARCHES" in candidates
