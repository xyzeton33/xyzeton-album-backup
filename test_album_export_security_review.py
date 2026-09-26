"""iPhone Album Backup security boundary regression tests

別モデルによるセキュリティレビューの指摘（v3.1.0時点）。v3.2.0ですべて修正済み。
改変された _album_state.json や、細工されたPhotos.sqlite(--db)が渡された場合に、
保存先の外や写真キャッシュの外へ影響できないことを確認する。

Run:
    python -m pytest -q test_album_export_security_review.py
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import album_export as engine


def test_prune_never_follows_state_path_outside_output(tmp_path):
    """A crafted _album_state.json path must never let prune touch files outside --out."""
    out = tmp_path / "backup"
    victim = tmp_path / "victim"
    out.mkdir()
    victim.mkdir()
    keep = victim / "KEEP.txt"
    keep.write_text("do not touch", encoding="utf-8")

    prev = {"albums": {"attacker-key": str(victim)}}

    engine.prune(str(out), {}, prev, set(), [])

    assert victim.is_dir()
    assert keep.read_text(encoding="utf-8") == "do not touch"


def test_reconcile_rename_never_moves_state_path_outside_output(tmp_path):
    """A crafted previous album path must not move an arbitrary external directory."""
    out = tmp_path / "backup"
    victim = tmp_path / "victim"
    out.mkdir()
    victim.mkdir()
    keep = victim / "KEEP.txt"
    keep.write_text("do not move", encoding="utf-8")

    prev = {"albums": {"same-key": str(victim)}}
    current = {"CurrentAlbum": "same-key"}

    engine.reconcile_renames(str(out), current, prev)

    assert victim.is_dir()
    assert keep.read_text(encoding="utf-8") == "do not move"
    assert not (out / "CurrentAlbum" / "KEEP.txt").exists()


def test_reconcile_special_never_moves_state_path_outside_output(tmp_path):
    """Crafted state.special values must not escape the backup root."""
    out = tmp_path / "backup"
    victim = tmp_path / "victim"
    out.mkdir()
    victim.mkdir()
    keep = victim / "KEEP.txt"
    keep.write_text("do not move", encoding="utf-8")

    engine.set_language("en")
    prev = {
        "special": {
            "media": str(victim),
            "unsorted": "_Unsorted",
            "removed": "_Removed",
            "types": {},
        }
    }

    engine.reconcile_special(str(out), prev)

    assert victim.is_dir()
    assert keep.read_text(encoding="utf-8") == "do not move"


def test_place_asset_rejects_relative_path_escape_from_cache(tmp_path):
    """A Photos.sqlite path containing '..' must not expose a local file outside the cache."""
    cache = tmp_path / "cache"
    dst = tmp_path / "backup" / "Album"
    cache.mkdir(parents=True)
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")

    ok = engine.place_asset("../secret.txt", str(cache), str(dst), placed=set())

    assert ok is False
    assert not (dst / "secret.txt").exists()


@pytest.mark.parametrize("rel", [
    "../secret.jpg",
    "DCIM/../secret.jpg",
    "DCIM/100APPLE/../../secret.jpg",
    r"..\secret.jpg",
    r"DCIM\..\secret.jpg",
])
def test_local_cache_mapping_rejects_traversal_forms(tmp_path, rel):
    """Any remote/database path mapped locally must remain a strict child of cache."""
    cache = tmp_path / "cache"
    cache.mkdir()
    outside = tmp_path / "secret.jpg"
    outside.write_bytes(b"secret")

    dst = tmp_path / "backup" / "Album"
    ok = engine.place_asset(rel, str(cache), str(dst), placed=set())

    assert ok is False
    assert not dst.exists() or not any(dst.iterdir())
