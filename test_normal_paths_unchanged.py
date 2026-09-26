"""リンクの無い通常ケースと、保存先ルート自体がリンクのケースで挙動が変わらないこと。"""
import os, pytest
import album_export as engine

def _outs(tmp_path, via_link):
    real = tmp_path / "real_out"; real.mkdir()
    if not via_link:
        return real, real
    link = tmp_path / "link_out"
    os.symlink(real, link, target_is_directory=True)
    return link, real

@pytest.mark.parametrize("via_link", [False, True])
def test_rename(tmp_path, via_link):
    out, real = _outs(tmp_path, via_link)
    (out / "A" / "Old").mkdir(parents=True); (out / "A" / "Old" / "x.jpg").write_bytes(b"1")
    engine.reconcile_renames(str(out), {"B/New": "k"}, {"albums": {"k": "A/Old"}})
    assert (real / "B" / "New" / "x.jpg").exists()

@pytest.mark.parametrize("via_link", [False, True])
def test_prune_both(tmp_path, via_link):
    out, real = _outs(tmp_path, via_link)
    alb = out / "P" / "Alb"; alb.mkdir(parents=True)
    (alb / "keep.jpg").write_bytes(b"1"); (alb / "stray.jpg").write_bytes(b"2")
    (out / "Gone").mkdir(); (out / "Gone" / "g.jpg").write_bytes(b"3")
    engine.prune(str(out), {"P/Alb": "k1"}, {"albums": {"k1": "P/Alb", "k2": "Gone"}},
                 {str(alb / "keep.jpg")}, [str(alb)])
    rm = real / engine.sp("removed")
    assert (real / "P" / "Alb" / "keep.jpg").exists()
    assert (rm / "P" / "Alb" / "stray.jpg").exists()
    assert (rm / "Gone" / "g.jpg").exists()

@pytest.mark.parametrize("via_link", [False, True])
def test_special_lang_switch(tmp_path, via_link):
    out, real = _outs(tmp_path, via_link)
    engine.set_language("en"); en = engine.special_names(); engine.set_language("ja")
    ja = engine.special_names()
    (out / en["unsorted"]).mkdir(); (out / en["unsorted"] / "u.jpg").write_bytes(b"1")
    sel_en = en["types"]["セルフィー"] if "セルフィー" in en["types"] else list(en["types"].values())[-1]
    key = [k for k, v in en["types"].items() if v == sel_en][0]
    (out / en["media"] / sel_en).mkdir(parents=True); (out / en["media"] / sel_en / "s.jpg").write_bytes(b"2")
    engine.reconcile_special(str(out), {"special": en})
    assert (real / ja["unsorted"] / "u.jpg").exists()
    assert (real / ja["media"] / ja["types"][key] / "s.jpg").exists()
