"""v3.3.1 セキュリティレビュー回帰テスト（実機不要）。F1〜F6: 保存先/キャッシュ内のリンクを辿って外へ書かない・動かさないこと"""
import asyncio, os, json
import album_export as engine

def _victim(tmp):
    v = tmp / "victim"; v.mkdir(); return v

# F1: prune (b) の退避先 _削除済み がリンクだと保存先の外へ移動する
def test_F1_prune_removed_root_link(tmp_path):
    out = tmp_path / "out"; out.mkdir(); victim = _victim(tmp_path)
    (out / "Album").mkdir()
    (out / "Album" / "old.jpg").write_text("photo")
    os.symlink(victim, out / engine.sp("removed"), target_is_directory=True)
    engine.prune(str(out), {"Album": "k"}, {"albums": {}}, set(), [str(out / "Album")])
    assert not (victim / "Album" / "old.jpg").exists()

# F2: _move_merge は移動先の「子」フォルダのリンクを見ない
def test_F2_move_merge_dst_child_link(tmp_path):
    out = tmp_path / "out"; out.mkdir(); victim = _victim(tmp_path)
    src = out / "Folder"; (src / "Sub").mkdir(parents=True)
    (src / "Sub" / "a.jpg").write_text("photo")
    dst = out / engine.sp("removed") / "Folder"; dst.mkdir(parents=True)
    os.symlink(victim, dst / "Sub", target_is_directory=True)
    engine.prune(str(out), {}, {"albums": {"gone": "Folder"}}, set(), [])
    assert not (victim / "a.jpg").exists()

# F3: _rename_tmp がリンクだと、改名途中の中身が保存先の外を経由する
def test_F3_rename_tmp_link(tmp_path):
    out = tmp_path / "out"; out.mkdir(); victim = _victim(tmp_path)
    (out / "Old").mkdir(); (out / "Old" / "a.jpg").write_text("photo")
    os.symlink(victim, out / engine.RENAME_TMP, target_is_directory=True)
    seen = {}
    orig = engine.shutil.move
    def spy(s, d):
        if os.path.realpath(d).startswith(str(victim)):
            seen["outside"] = d
        return orig(s, d)
    engine.shutil.move = spy
    try:
        engine.reconcile_renames(str(out), {"New": "KEY"}, {"albums": {"KEY": "Old"}})
    finally:
        engine.shutil.move = orig
    assert "outside" not in seen

# F4: 固定名ファイルへの書き込みがリンクを辿る（save_state の .tmp）
def test_F4_state_tmp_link_clobber(tmp_path):
    out = tmp_path / "out"; out.mkdir(); victim = _victim(tmp_path)
    target = victim / "important.docx"; target.write_text("ORIGINAL")
    os.symlink(target, out / (engine.STATE_FILE + ".tmp"))
    engine.save_state(str(out), {}, {})
    assert target.read_text() == "ORIGINAL"

# F5: キャッシュの .part がリンクだと、ダウンロード内容が外のファイルへ書かれる
class FakeAfc:
    async def fopen(self, p, m): return 1
    async def fread(self, h, n): return b"X" * n
    async def fclose(self, h): pass
    async def fseek(self, *a): pass
def test_F5_part_link_clobber(tmp_path):
    cache = tmp_path / "cache"; (cache / "DCIM" / "100APPLE").mkdir(parents=True)
    victim = _victim(tmp_path); target = victim / "important.docx"; target.write_text("ORIGINAL")
    local = engine.safe_cache_path(str(cache), "DCIM/100APPLE/IMG_0001.JPG")
    assert local is not None
    os.symlink(target, local + ".part")
    # 小さいファイルは .part を先に消すので、再開対象（RESUME_MIN以上）でメタも用意
    size = engine.RESUME_MIN
    with open(local + ".part.size", "w") as f: f.write(str(size))
    asyncio.run(engine.download(FakeAfc(), "DCIM/100APPLE/IMG_0001.JPG", local, size))
    assert target.read_text() == "ORIGINAL"

# F6: Live Photo の .MOV は safe_cache_path を通らない
def test_F6_livephoto_mov_link(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    cache = tmp_path / "cache"; (cache / "DCIM" / "100APPLE").mkdir(parents=True)
    victim = _victim(tmp_path); secret = victim / "secret.txt"; secret.write_text("SECRET")
    os.utime(secret, (1000000000, 1000000000))
    (cache / "DCIM" / "100APPLE" / "IMG_0001.HEIC").write_text("img")
    os.symlink(secret, cache / "DCIM" / "100APPLE" / "IMG_0001.MOV")
    placed = set()
    engine.place_asset("DCIM/100APPLE/IMG_0001.HEIC", str(cache), str(out / "Album"),
                       {"DCIM/100APPLE/IMG_0001.HEIC": 1700000000}, True, placed, out_root=str(out))
    files = sorted(p.name for p in (out / "Album").iterdir())
    assert not any(f.endswith(".MOV") for f in files) and secret.stat().st_mtime == 1000000000
