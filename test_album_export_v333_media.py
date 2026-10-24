"""v3.3.3: メディアタイプを「当てはまる全部」に入れる / _cache_DCIM を隠す のテスト（実機不要）

背景（GitHub Issue #1・#2）:
- v3.3.2 までは1枚を1種類のメディアタイプにだけ入れていた。iPhoneの写真アプリは重ねて表示するため、
  奥行き情報つきの Live Photos がポートレートだけに入り、Live Photos の件数が写真アプリより 764 少なかった
  （iPhone 17 Pro Max / iOS 27.0.1）。
- 作者の iPhone 11 Pro Max（iOS 27.0.1）では、写真アプリのセルフィー 76・ビデオ 85 が、
  「前面カメラの Live／ポートレートもセルフィー」「画面収録もビデオ」とした場合の数と一致した。

ここでは、実機の診断ファイル（_メディアタイプ診断.txt）の値の組み合わせと件数をそのまま使い、
写真アプリの件数と一致することを確かめる。

実行例:
    python -m pytest -q test_album_export_v333_media.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import album_export as engine


@pytest.fixture(autouse=True)
def quiet_engine():
    engine.CANCEL.clear()
    old_log, old_handler = engine.log, engine._event_handler
    engine.set_logger(lambda *a, **k: None)
    engine.set_event_handler(None)
    engine.set_language("ja")
    yield
    engine.CANCEL.clear()
    engine.set_logger(old_log)
    engine.set_event_handler(old_handler)


def _count(rows):
    """診断ファイルの行（ZKIND, ZKINDSUBTYPE, ZPLAYBACKSTYLE, ZDEPTHTYPE, ZCAMERACAPTUREDEVICE, 拡張子, 件数）から種類別の件数"""
    counts = {}
    for kind, sub, pb, dep, cam, ext, n in rows:
        for k in engine.classify_media_all(kind, sub, pb, dep, cam, "x" + ext.lower()):
            counts[k] = counts.get(k, 0) + n
    return counts


# iPhone 17 Pro Max / iOS 27.0.1（GitHub Issue #1 で共有された診断ファイル）
ROWS_17PM = [
    (0, 1, 1, 0, 0, ".JPG", 3843), (0, 0, 1, 0, 0, ".JPG", 2213), (0, 2, 3, 0, 0, ".JPG", 628),
    (0, 2, 3, 1, 1, ".JPG", 347), (0, 2, 3, 0, 0, ".HEIC", 336), (1, 0, 4, 0, 0, ".MP4", 231),
    (0, 2, 3, 1, 0, ".JPG", 175), (0, 2, 3, 1, 1, ".HEIC", 169), (0, 2, 3, 1, 0, ".HEIC", 73),
    (1, 0, 4, 0, 0, ".MOV", 46), (0, 0, 1, 0, 1, ".JPG", 33), (0, 2, 1, 0, 0, ".JPG", 32),
    (0, 10, 1, 0, 0, ".PNG", 22), (0, 0, 1, 0, 0, ".PNG", 19), (0, 0, 1, 1, 0, ".JPG", 15),
    (0, 0, 1, 0, 0, ".JPEG", 13), (0, 2, 3, 0, 1, ".JPG", 6), (0, 2, 1, 0, 0, ".HEIC", 6),
    (0, 0, 1, 0, 1, ".HEIC", 4), (0, 0, 1, 1, 1, ".JPG", 2), (0, 0, 1, 0, 0, ".HEIC", 1),
    (0, 2, 3, 0, 1, ".HEIC", 1), (0, 1, 1, 0, 0, ".PNG", 1), (0, 0, 2, 0, 0, ".GIF", 1),
]

# iPhone 11 Pro Max / iOS 27.0.1（作者。2026-10-20 の診断ファイル）
ROWS_11PM = [
    (0, 10, 1, 0, 0, ".PNG", 61935), (0, 0, 1, 0, 0, ".JPG", 3711), (0, 2, 3, 0, 0, ".JPG", 1905),
    (0, 0, 1, 1, 0, ".JPG", 1837), (0, 0, 1, 0, 0, ".PNG", 724), (0, 0, 1, 0, 0, ".JPEG", 301),
    (0, 2, 1, 0, 0, ".JPG", 56), (1, 0, 4, 0, 0, ".MP4", 40), (0, 1, 1, 0, 0, ".JPG", 38),
    (0, 0, 1, 0, 1, ".JPG", 26), (0, 0, 1, 1, 1, ".JPG", 25), (0, 2, 3, 0, 1, ".JPG", 25),
    (1, 0, 4, 0, 0, ".MOV", 25), (1, 103, 4, 0, 0, ".MP4", 19), (0, 0, 1, 0, 0, ".WEBP", 5),
    (0, 1, 1, 0, 0, ".PNG", 3), (0, 0, 1, 1, 0, ".JPEG", 1), (0, 0, 2, 0, 0, ".GIF", 1),
]


def test_counts_match_photos_app_iphone17promax():
    c = _count(ROWS_17PM)
    # 報告者が写真アプリで確認した数
    assert c["Live Photos"] == 1773
    assert c["ポートレート"] == 781
    assert c["パノラマ"] == 3844
    assert c["ビデオ"] == 277
    assert c["スクリーンショット"] == 22


def test_counts_match_photos_app_iphone11promax():
    c = _count(ROWS_11PM)
    # 作者が写真アプリで確認した数（セルフィー 76、ビデオは同日の別の実行で 85 = ビデオ 66 + 画面録画 19）
    assert c["セルフィー"] == 26 + 25 + 25 == 76
    assert c["ビデオ"] == 40 + 25 + 19 == 84
    assert c["画面録画"] == 19
    # 重なりの無い種類は v3.3.2 と同じ数
    assert c["Live Photos"] == 1986
    assert c["ポートレート"] == 1863
    assert c["スクリーンショット"] == 61935


def test_primary_type_is_unchanged_from_v332():
    """classify_media（先頭の1種類）は v3.3.2 までと同じ結果を返す（既存の呼び出し元のため）。"""
    expect = {
        (0, 2, 3, 1, 1, ".JPG"): "ポートレート",   # Live + 奥行き + 前面
        (0, 2, 3, 0, 1, ".JPG"): "Live Photos",    # Live + 前面
        (0, 0, 1, 0, 1, ".JPG"): "セルフィー",
        (1, 103, 4, 0, 0, ".MP4"): "画面録画",
        (1, 0, 4, 0, 0, ".MOV"): "ビデオ",
        (0, 0, 2, 0, 0, ".GIF"): "アニメーション",
        (0, 0, 1, 0, 0, ".JPG"): None,
    }
    for (kind, sub, pb, dep, cam, ext), want in expect.items():
        assert engine.classify_media(kind, sub, pb, dep, cam, "x" + ext.lower()) == want


def test_videos_are_never_selfies():
    """前面カメラの動画がセルフィーに入るかは未確認なので、入れない。"""
    assert engine.classify_media_all(1, 0, 4, 0, 1, "x.mov") == ["ビデオ"]


def test_all_types_are_in_media_types_order():
    got = engine.classify_media_all(0, 2, 3, 1, 1, "x.jpg")
    assert got == ["ポートレート", "Live Photos", "セルフィー"]


# ---------------------------------------------------------------------------
# 振り分けの通し確認（--db と --skip-pull で、iPhone なしに run() を動かす）

def _make_db(path: Path):
    con = sqlite3.connect(path)
    c = con.cursor()
    c.execute("CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZKIND INTEGER, ZPARENTFOLDER INTEGER, ZUUID TEXT)")
    c.execute("CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZDIRECTORY TEXT, ZFILENAME TEXT, ZDATECREATED REAL,"
              " ZKIND INTEGER, ZKINDSUBTYPE INTEGER, ZPLAYBACKSTYLE INTEGER, ZDEPTHTYPE INTEGER)")
    c.execute("CREATE TABLE ZADDITIONALASSETATTRIBUTES (Z_PK INTEGER PRIMARY KEY, ZASSET INTEGER, ZCAMERACAPTUREDEVICE INTEGER)")
    c.execute("CREATE TABLE Z_1ASSETS (Z_1ALBUMS INTEGER, Z_3ASSETS INTEGER)")
    for i, name in enumerate(["家族", "旅行", "猫"], 1):
        c.execute("INSERT INTO ZGENERICALBUM VALUES (?,?,?,?,?)", (i, name, 2, None, f"uuid{i}"))
    assets = [
        # pk, file, kind, sub, playback, depth, camera
        (101, "IMG_0001.JPG", 0, 2, 3, 1, 1),   # Live + 奥行き + 前面 → ポートレート・Live・セルフィー
        (102, "IMG_0002.JPG", 0, 2, 3, 0, 0),   # Live だけ
        (103, "IMG_0003.MP4", 1, 103, 4, 0, 0), # 画面録画 → 画面録画・ビデオ
        (104, "IMG_0004.JPG", 0, 0, 1, 0, 0),   # ふつうの写真
    ]
    for j, (pk, fn, kind, sub, pb, dep, cam) in enumerate(assets):
        c.execute("INSERT INTO ZASSET VALUES (?,?,?,?,?,?,?,?)", (pk, "DCIM/100APPLE", fn, 700000000.0 + j, kind, sub, pb, dep))
        c.execute("INSERT INTO ZADDITIONALASSETATTRIBUTES (ZASSET, ZCAMERACAPTUREDEVICE) VALUES (?,?)", (pk, cam))
    for alb, pk in ((1, 101), (2, 102), (3, 103)):
        c.execute("INSERT INTO Z_1ASSETS VALUES (?,?)", (alb, pk))
    con.commit()
    con.close()
    return [a[1] for a in assets]


def _args(out, db, **kw):
    v = dict(out=str(out), cache=None, list=False, skip_pull=True, refresh_db=False, db=str(db),
             no_date_prefix=True, media_types="all", lang="ja", prune=False, gui=False, fast_rescan=False)
    v.update(kw)
    return argparse.Namespace(**v)


def _files_under(root: Path):
    return {p.name: p for p in root.rglob("*") if p.is_file()}


def test_run_places_each_item_in_every_matching_media_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))
    db = tmp_path / "Photos.sqlite"
    names = _make_db(db)
    out = tmp_path / "out"
    cache = out / "_cache_DCIM" / "DCIM" / "100APPLE"
    cache.mkdir(parents=True)
    for n in names:
        (cache / n).write_bytes(n.encode())
    (cache / "IMG_0001.MOV").write_bytes(b"live-video")   # Live Photo の動画

    asyncio.run(engine.run(_args(out, db)))

    media = out / "_メディアタイプ"
    by_type = {d.name: _files_under(d) for d in media.iterdir() if d.is_dir()}
    assert set(by_type["ポートレート"]) == {"IMG_0001.JPG", "IMG_0001.MOV"}
    assert set(by_type["セルフィー"]) == {"IMG_0001.JPG", "IMG_0001.MOV"}
    assert set(by_type["Live Photos"]) == {"IMG_0001.JPG", "IMG_0001.MOV", "IMG_0002.JPG"}
    assert set(by_type["画面録画"]) == {"IMG_0003.MP4"}
    assert set(by_type["ビデオ"]) == {"IMG_0003.MP4"}
    assert "IMG_0004.JPG" not in {n for files in by_type.values() for n in files}

    # どれも実体と同じファイル（ハードリンク）で、容量は増えていない
    src = cache / "IMG_0001.JPG"
    for t in ("ポートレート", "セルフィー", "Live Photos"):
        assert os.path.samefile(by_type[t]["IMG_0001.JPG"], src)
    assert os.stat(src).st_nlink >= 5   # 実体 + アルバム + 3種類

    # アルバムと _未分類 は今までどおり
    assert (out / "家族" / "IMG_0001.JPG").exists()
    assert (out / "家族" / "IMG_0001.MOV").exists()
    assert any(p.name == "IMG_0004.JPG" for p in (out / "_未分類").rglob("*"))


def test_rerun_with_prune_keeps_multi_type_links(tmp_path, monkeypatch):
    """2回目（「_削除済みへ移す」オン）でも、重ねて置いたリンクを『外れた写真』と誤認して動かさない。"""
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))
    db = tmp_path / "Photos.sqlite"
    names = _make_db(db)
    out = tmp_path / "out"
    cache = out / "_cache_DCIM" / "DCIM" / "100APPLE"
    cache.mkdir(parents=True)
    for n in names:
        (cache / n).write_bytes(n.encode())

    asyncio.run(engine.run(_args(out, db)))
    before = sorted(str(p.relative_to(out)) for p in (out / "_メディアタイプ").rglob("*") if p.is_file())
    asyncio.run(engine.run(_args(out, db, prune=True)))
    after = sorted(str(p.relative_to(out)) for p in (out / "_メディアタイプ").rglob("*") if p.is_file())

    assert before == after
    removed = out / "_削除済み"
    assert not removed.exists() or not any(p.is_file() for p in removed.rglob("*"))


def test_upgrade_from_single_type_backup_only_adds_links(tmp_path, monkeypatch):
    """v3.3.2 で作ったバックアップ（1種類だけ）に v3.3.3 で続きを足すと、リンクが増えるだけで何も消えない。"""
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))
    db = tmp_path / "Photos.sqlite"
    names = _make_db(db)
    out = tmp_path / "out"
    cache = out / "_cache_DCIM" / "DCIM" / "100APPLE"
    cache.mkdir(parents=True)
    for n in names:
        (cache / n).write_bytes(n.encode())

    # v3.3.2 の動き（先頭の1種類だけ）を再現して1回目を実行
    orig_all = engine.classify_media_all
    monkeypatch.setattr(engine, "classify_media_all", lambda *a: orig_all(*a)[:1])
    asyncio.run(engine.run(_args(out, db, prune=True)))
    first = {str(p.relative_to(out)) for p in (out / "_メディアタイプ").rglob("*") if p.is_file()}

    monkeypatch.setattr(engine, "classify_media_all", orig_all)
    asyncio.run(engine.run(_args(out, db, prune=True)))
    second = {str(p.relative_to(out)) for p in (out / "_メディアタイプ").rglob("*") if p.is_file()}

    assert first < second                      # 増えただけ
    added = {os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(p)))) for p in second - first}
    assert added == {"Live Photos", "セルフィー", "ビデオ"}
    removed = out / "_削除済み"
    assert not removed.exists() or not any(p.is_file() for p in removed.rglob("*"))


# ---------------------------------------------------------------------------
# _cache_DCIM を隠す（Windows のみ動く処理。ここでは呼ばれ方を確かめる）

def test_new_default_cache_is_hidden_once(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))
    db = tmp_path / "Photos.sqlite"
    _make_db(db)
    calls = []
    monkeypatch.setattr(engine, "_hide_folder_only", lambda p: calls.append(p) or True)
    out = tmp_path / "out"

    asyncio.run(engine.run(_args(out, db)))
    assert calls == [str(out / "_cache_DCIM")]

    calls.clear()
    asyncio.run(engine.run(_args(out, db)))   # 2回目（既にある）は触らない
    assert calls == []


def test_existing_or_custom_cache_is_not_hidden(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "app_dir", lambda: str(tmp_path))
    db = tmp_path / "Photos.sqlite"
    _make_db(db)
    calls = []
    monkeypatch.setattr(engine, "_hide_folder_only", lambda p: calls.append(p) or True)

    out1 = tmp_path / "out1"
    (out1 / "_cache_DCIM").mkdir(parents=True)          # 以前のバージョンで作ったもの
    asyncio.run(engine.run(_args(out1, db)))

    out2 = tmp_path / "out2"
    asyncio.run(engine.run(_args(out2, db, cache=str(tmp_path / "mycache"))))   # 場所を指定したもの
    assert calls == []


def test_hide_folder_only_is_noop_outside_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.sys, "platform", "linux")
    assert engine._hide_folder_only(str(tmp_path)) is False
