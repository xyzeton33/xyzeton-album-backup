"""iPhone Album Backup v3.2.2 final security follow-up tests (no real iPhone required)

Run:
    python -m pytest -q test_album_export_v322_final_security.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import album_export as engine


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unavailable")
def test_prune_does_not_traverse_managed_album_symlink(tmp_path):
    """prune's managed_dirs loop must not traverse an album symlink/junction outside --out."""
    out = tmp_path / "out"
    victim = tmp_path / "victim"
    out.mkdir()
    victim.mkdir()

    keep = victim / "KEEP.txt"
    keep.write_text("do not move", encoding="utf-8")

    os.symlink(victim, out / "Album", target_is_directory=True)

    engine.prune(
        str(out),
        {"Album": "current-key"},
        {"albums": {}},
        set(),
        [str(out / "Album")],
    )

    assert keep.exists()
    assert not (out / engine.sp("removed") / "Album" / "KEEP.txt").exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unavailable")
def test_place_asset_rejects_linkish_parent_component(tmp_path):
    """A non-link leaf below a link/junction parent must not redirect output outside --out."""
    cache = tmp_path / "cache"
    (cache / "DCIM").mkdir(parents=True)
    (cache / "DCIM" / "A.JPG").write_bytes(b"PHOTO")

    out = tmp_path / "out"
    victim = tmp_path / "victim"
    out.mkdir()
    victim.mkdir()

    os.symlink(victim, out / "Parent", target_is_directory=True)
    dst = out / "Parent" / "Album"  # dst itself is not a symlink

    ok = engine.place_asset("DCIM/A.JPG", str(cache), str(dst), placed=set())

    assert ok is False
    assert not (victim / "Album" / "A.JPG").exists()


@pytest.mark.parametrize("special", [
    {"types": []},
    {"types": {}, "media": 123},
    {"types": {}, "unsorted": 123},
    {"types": {}, "removed": ["bad"]},
])
def test_malformed_nested_special_state_does_not_crash(tmp_path, special):
    """Nested values in a syntactically-valid but tampered state file must be normalized/rejected."""
    state_file = tmp_path / engine.STATE_FILE
    state_file.write_text(
        json.dumps({"albums": {}, "special": special}),
        encoding="utf-8",
    )

    state = engine.load_state(str(tmp_path))
    engine.reconcile_special(str(tmp_path), state)
