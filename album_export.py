#!/usr/bin/env python3
r"""
iPhone Album Backup - backup engine (Photos.sqlite parser + AFC downloader)
Copyright (C) 2026  XYZETON

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

Project: https://github.com/XYZETON/iphone-album-backup
Developed with assistance from Anthropic Claude.
album_export.py  ── iPhoneの「アルバム」構造を保ったままWindowsへバックアップ

手順(自動):
  1. 写真DB(Photos.sqlite)をUSB経由で取得        … 小さい・一瞬
  2. DBを解析して「フォルダ/アルバム → 写真」対応表を作成
  3. 写真の実体(DCIM)をキャッシュへダウンロード    … 本体。途中で切れても再実行で続きから
  4. 出力先/フォルダ名/アルバム名/ にハードリンクで振り分け（容量ほぼゼロ・一瞬）

使い方:
  python album_export.py --list                 … アルバム一覧だけ表示(ダウンロードしない)
  python album_export.py --out D:\iPhoneAlbums  … 本実行
"""
import argparse, asyncio, errno, json, os, shutil, sqlite3, sys, time, uuid

# Windowsのコマンドプロンプトで日本語アルバム名が化けないように
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


import threading

LANG = "ja"   # "ja" / "en"


def set_language(lang):
    global LANG
    LANG = "en" if str(lang).lower().startswith("en") else "ja"


def t(ja, en):
    return ja if LANG == "ja" else en


CANCEL = threading.Event()   # GUIの「中止」ボタンで立てる


class Cancelled(Exception):
    """利用者が中止した"""


class ConnectionLost(Exception):
    """iPhoneとの接続が切れ、再接続もできなかった"""


def request_cancel():
    CANCEL.set()


_event_handler = None  # (kind, message) を受け取る。GUIがポップアップ用に登録する


def set_event_handler(fn):
    global _event_handler
    _event_handler = fn


_progress_handler = None


def set_progress_handler(fn):
    """GUIが確定進捗を受け取るためのフック。
    fn(phase, done, total, done_bytes, total_bytes, current_name)"""
    global _progress_handler
    _progress_handler = fn


def _progress(phase, done, total, done_bytes=0, total_bytes=0, name=""):
    if _progress_handler:
        try:
            _progress_handler(phase, done, total, done_bytes, total_bytes, name)
        except Exception:
            pass


def _event(kind, message=""):
    if _event_handler:
        try:
            _event_handler(kind, message)
        except Exception:
            pass


def _check_cancel():
    if CANCEL.is_set():
        raise Cancelled()


def _default_log(msg="", end="\n", flush=True):
    print(msg, end=end, flush=flush)


log = _default_log  # GUI側から差し替え可能

def set_logger(fn):
    global log
    log = fn


def _exe_dir():
    """exe化(PyInstaller)時は exe の隣、通常時はスクリプトの隣"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


_APP_DIR = None


def app_dir():
    """設定と写真データベース(数GB)の置き場所。
    通常は exe の隣（フォルダごと別ドライブへ移動でき、DBも一緒に運べる）。
    Program Files など書き込めない場所に置かれた場合だけ、ユーザーのデータ領域に逃がす。"""
    global _APP_DIR
    if _APP_DIR:
        return _APP_DIR
    base = _exe_dir()
    # 固定名だと、利用者が元々同じ名前のファイルを持っていた場合に
    # 上書き→削除してしまう。毎回ランダムな名前で、自分が新規作成できたものだけ消す。
    token = f".iab_writetest_{uuid.uuid4().hex}"
    probe = os.path.join(base, token)
    made = False
    try:
        with open(probe, "xb") as f:
            f.write(b"x")
        made = True
        _APP_DIR = base
    except OSError:
        fallback = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        _APP_DIR = os.path.join(fallback, "iPhoneAlbumBackup")
        os.makedirs(_APP_DIR, exist_ok=True)
    finally:
        if made:
            try:
                os.remove(probe)
            except OSError:
                pass
    return _APP_DIR

try:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.afc import AfcService
except ImportError:
    sys.exit("pymobiledevice3 が入っていません。先に  pip install pymobiledevice3  を実行してください。 / pymobiledevice3 is not installed. Run: pip install pymobiledevice3")

DB_CANDIDATES = ["PhotoData/Photos.sqlite", "PhotoData/PhotoData/Photos.sqlite"]
CHUNK = 4 * 1024 * 1024  # 4MB
RESUME_MIN = 20 * 1024 * 1024   # これ以上のファイルだけ「途中から再開」用の情報を残す
_MADE_DIRS = set()              # 作成済みフォルダ（makedirsの連発を避ける）
# 特殊フォルダ名（言語別）。内部キーは固定、表示/フォルダ名だけ切り替える
SPECIAL = {
    "unsorted": ("_未分類", "_Unsorted"),
    "removed": ("_削除済み", "_Removed"),
    "media": ("_メディアタイプ", "_MediaTypes"),
    "nodate": ("日付不明", "UnknownDate"),
}
MEDIA_NAMES = {
    "画面録画": ("画面録画", "Screen Recordings"), "スローモーション": ("スローモーション", "Slo-mo"),
    "タイムラプス": ("タイムラプス", "Time-lapse"), "ビデオ": ("ビデオ", "Videos"),
    "スクリーンショット": ("スクリーンショット", "Screenshots"), "パノラマ": ("パノラマ", "Panoramas"),
    "アニメーション": ("アニメーション", "Animated"), "ポートレート": ("ポートレート", "Portrait"),
    "Live Photos": ("Live Photos", "Live Photos"), "セルフィー": ("セルフィー", "Selfies"),
}


def sp(key):
    return t(*SPECIAL[key])


def media_name(key):
    return t(*MEDIA_NAMES[key])


def special_names():
    """今の言語での特殊フォルダ名一式（状態ファイルに記録し、言語切替時のリネームに使う）"""
    return {"unsorted": sp("unsorted"), "removed": sp("removed"), "media": sp("media"), "nodate": sp("nodate"),
            "types": {k: media_name(k) for k in MEDIA_TYPES}}
# iPhoneの「メディアタイプ」に対応。上から順に判定し、最初に当たった1種類だけに入れる（重複しない）
MEDIA_TYPES = ["画面録画", "スローモーション", "タイムラプス", "ビデオ",
               "スクリーンショット", "パノラマ", "アニメーション", "ポートレート", "Live Photos", "セルフィー"]
STATE_FILE = "_album_state.json"
RENAME_TMP = "_rename_tmp"
CACHE_DIR = "_cache_DCIM"
KIND_USER_ALBUM, KIND_FOLDER = 2, 4000
APPLE_EPOCH = 978307200  # 2001-01-01 00:00:00 UTC (Core Dataの基準時刻)


# ============================================================ 接続
def _amds_listening(timeout=1.0):
    """WindowsではAppleのサービス(Apple Mobile Device Service)が127.0.0.1:27015で待ち受ける。
    ここに繋がるかどうかで「サービスの問題」か「ケーブル/信頼の問題」かを切り分けられる。"""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 27015), timeout=timeout):
            return True
    except OSError:
        return False


def connection_help(err):
    detail = f"{type(err).__name__}: {err}" if str(err) else type(err).__name__
    if sys.platform == "win32" and not _amds_listening():
        return t(
            "❌ iPhoneに接続できませんでした。\n"
            "   原因: Windows側の『Apple Mobile Device Service』が動いていません。\n"
            "   （このツールはiTunesと同じ仕組みで通信します。\n"
            "     エクスプローラーでiPhoneの中身が見えるかどうかは別の仕組みなので、判断材料になりません）\n\n"
            "   直し方（上から順に）:\n"
            "   1) Windowsキー+R →『services.msc』→ 一覧の『Apple Mobile Device Service』を右クリック→開始\n"
            "      （スタートアップの種類は『自動』に）\n"
            "   2) 一覧に無い場合は、Microsoft Storeの『Appleデバイス』アプリを入れて、一度起動しiPhoneを認識させる\n"
            "   3) それでも駄目なら、iTunes と Appleデバイス の両方を入れている状態が原因のことがあります。\n"
            "      片方だけにして、PCを再起動してからもう一度お試しください\n"
            "   4) 再起動後、まず『Appleデバイス』またはiTunesでiPhoneが見えるか確認してください\n"
            f"\n   詳細: {detail}",
            "❌ Could not connect to the iPhone.\n"
            "   Cause: the Windows service 'Apple Mobile Device Service' is not running.\n"
            "   (This tool talks to the iPhone the same way iTunes does. Seeing the device in\n"
            "    File Explorer uses a different mechanism and does not mean this will work.)\n\n"
            "   How to fix, in order:\n"
            "   1) Win+R -> 'services.msc' -> right-click 'Apple Mobile Device Service' -> Start\n"
            "      (set Startup type to Automatic)\n"
            "   2) If it is not listed, install the 'Apple Devices' app from the Microsoft Store,\n"
            "      open it once and let it detect your iPhone\n"
            "   3) Having both iTunes and Apple Devices installed can conflict. Keep only one,\n"
            "      then restart the PC and try again\n"
            "   4) After restarting, check that Apple Devices (or iTunes) can see the iPhone first\n"
            f"\n   Details: {detail}")
    return t(
        "❌ iPhoneに接続できませんでした。\n"
        "   確認すること:\n"
        "   1) iPhoneのロックを解除し『このコンピュータを信頼』をタップしたか\n"
        "      （一度も出ていない場合は、ケーブルを挿し直してください）\n"
        "   2) Apple純正のUSBケーブルか\n"
        "      （非純正は動作保証外です。エクスプローラーで中身が見えても、\n"
        "       このツールでは繋がらない例が実際にあります。純正でお試しください）\n"
        "   3) 別のUSBポートに挿し替える（USBハブ経由だと不安定なことがあります）\n"
        f"\n   詳細: {detail}",
        "❌ Could not connect to the iPhone.\n"
        "   Check:\n"
        "   1) Unlock the iPhone and tap 'Trust This Computer'\n"
        "      (if the prompt never appeared, unplug and replug the cable)\n"
        "   2) Use an Apple original USB cable (third-party cables are unsupported;\n"
        "      being visible in File Explorer does not mean this tool can connect)\n"
        "   3) Try a different USB port (hubs can be unreliable)\n"
        f"\n   Details: {detail}")


async def connect():
    try:
        return await create_using_usbmux()
    except Exception as e:
        raise SystemExit(connection_help(e))


# ============================================================ DB取得
async def pull_one(afc, remote, local, label):
    """大きな単一ファイルを .part に書きながら取得。中止/切断後は .part の続きから再開する（fseek）。
    get_file_contents() は内部で bytes+= を繰り返すため数GB級で極端に遅くなるので使わない。"""
    size = int((await afc.stat(remote))["st_size"])
    part = local + ".part"
    meta = part + ".size"  # 取得開始時のリモートサイズ。変わっていたら最初からやり直す
    start = 0
    if os.path.exists(part) and os.path.exists(meta):
        try:
            if int(open(meta).read().strip()) == size and os.path.getsize(part) <= size:
                start = os.path.getsize(part)
        except Exception:
            start = 0
    if start:
        log(t(f"   {label}: 前回の続き（{start/1024**2:,.0f} MB）から再開します", f"   {label}: resuming from {start/1024**2:,.0f} MB"))
    else:
        with open(meta, "w") as f:
            f.write(str(size))
    h = await afc.fopen(remote, "r")
    if start:
        await afc.fseek(h, start, os.SEEK_SET)
    done = start
    t0 = time.time()
    try:
        with open(part, "ab" if start else "wb") as f:
            while done < size:
                _check_cancel()
                chunk = await afc.fread(h, min(CHUNK, size - done))
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if size > 20 * 1024 * 1024:
                    pct = done / size * 100
                    log(f"\r   {label}: {done/1024**2:8.1f}/{size/1024**2:8.1f} MB ({pct:5.1f}%)", end="")
                    _progress("db", done, size, done, size, label)
    finally:
        try:
            await afc.fclose(h)
        except Exception:
            pass
    if done != size:
        raise IOError(t(f"{label}: サイズ不一致 ({done}/{size})", f"{label}: size mismatch ({done}/{size})"))
    os.replace(part, local)
    try:
        os.remove(meta)
    except OSError:
        pass
    if size > 20 * 1024 * 1024:
        log(t(f"  完了 {time.time()-t0:.0f}秒", f"  done in {time.time()-t0:.0f}s"))


async def pull_photos_db(afc, dbdir, refresh=False):
    """写真DBを取得する。main / -wal / -shm は必ず「1セット」として扱う。
    古い -wal が残ったまま新しい main を開くと、SQLiteが古いWALを適用してしまい、
    取り直したはずのアルバム情報が古いままになる（実測で再現）。"""
    src = None
    for c in DB_CANDIDATES:
        if await afc.exists(c):
            src = c
            break
    if not src:
        sys.exit(t("写真DB(Photos.sqlite)に届きません。先に probe.py を実行して判定してください。",
                   "Cannot reach the Photos database (Photos.sqlite). Run probe.py first."))
    os.makedirs(dbdir, exist_ok=True)
    local = os.path.join(dbdir, "Photos.sqlite")

    # 端末側の現在の構成を調べる
    remote_sizes = {}
    for ext in ("", "-wal", "-shm"):
        if await afc.exists(src + ext):
            remote_sizes[ext] = int((await afc.stat(src + ext))["st_size"])

    # 1つでも取り直すなら、セット全体を作り直す（世代が混ざらないように）。
    # 端末側からWAL/SHMが消えた場合も作り直す。古いWALが残っていると
    # SQLiteがそれを適用し、新しいDBを開いても古い内容が読まれてしまう。
    presence_changed = any(
        os.path.exists(local + ext) != (ext in remote_sizes) for ext in ("-wal", "-shm"))
    need = refresh or presence_changed or any(
        not os.path.exists(local + e) or os.path.getsize(local + e) != sz
        for e, sz in remote_sizes.items())
    if not need:
        log(t("   写真データベース: 取得済みを再利用（再取得するには『アルバム情報を取り直す』）",
              "   Photos database: reusing the previous copy (tick 'Refresh album info' to fetch again)"))
        return local

    for ext in ("", "-wal", "-shm"):
        if ext in remote_sizes:
            await pull_one(afc, src + ext, local + ext, t(f"写真データベース{ext}", f"Photos database{ext}"))
        else:
            # 端末側に無いものは、前回分を残さない（古いWALの適用を防ぐ）
            for leftover in (local + ext, local + ext + ".part", local + ext + ".part.size"):
                if ext and os.path.exists(leftover):
                    try:
                        os.remove(leftover)
                        log(t(f"   古い {os.path.basename(leftover)} を削除しました",
                              f"   removed stale {os.path.basename(leftover)}"))
                    except OSError:
                        pass
    return local


# ============================================================ DB解析
def dump_schema(cur, path):
    """検出失敗時の診断用: Z_/ZASSET/ZGENERICALBUM 系の表と列を書き出す"""
    with open(path, "w", encoding="utf-8") as f:
        names = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
        for name in names:
            u = name.upper()
            if u.startswith("Z_") or "ASSET" in u or "ALBUM" in u:
                cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{name}")')]
                try:
                    n = cur.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                except Exception:
                    n = "?"
                f.write(f"{name} (rows={n}): {', '.join(cols)}\n")


def find_join_table(cur, cols):
    """アルバム⇔写真の中間テーブルを、名前ではなく中身から特定する。

    中間テーブル名は `Z_28ASSETS` のようにiOSの版で数字が変わるため名前に頼れない。
    ただし「両列の整数がPK集合に含まれる」だけでは、無関係な統計表なども条件を満たす。
    そこで中間テーブルとして成立する条件を積み増して確認する。
    それでも推定であることに変わりはないので、確信が持てない場合は None を返して停止する。
    """
    alb_pks = {r[0] for r in cur.execute("SELECT Z_PK FROM ZGENERICALBUM").fetchall()}
    ast_pks = {r[0] for r in cur.execute("SELECT Z_PK FROM ZASSET").fetchall()}
    if len(alb_pks) < 1 or len(ast_pks) < 1:
        return None
    user_albums = {r[0] for r in cur.execute(
        f"SELECT Z_PK FROM ZGENERICALBUM WHERE ZKIND={KIND_USER_ALBUM}").fetchall()}

    names = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Z%'").fetchall()]
    cands = []
    for name in names:
        if name in ("ZASSET", "ZGENERICALBUM"):
            continue
        cs = [c for c in cols(name) if not c.startswith("Z_FOK")]
        if not (2 <= len(cs) <= 4):
            continue
        rows = cur.execute(f'SELECT {", ".join(cs)} FROM "{name}"').fetchall()
        if len(rows) < 3:
            continue
        for ai, ac in enumerate(cs):
            for si, sc in enumerate(cs):
                if ai == si:
                    continue
                a_vals = [r[ai] for r in rows]
                s_vals = [r[si] for r in rows]
                if not (all(v in alb_pks for v in a_vals) and all(v in ast_pks for v in s_vals)):
                    continue
                pairs = {(a, b) for a, b in zip(a_vals, s_vals)}
                # 中間テーブルなら (アルバム, 写真) の組は重複しない。
                # 統計表などは同じ組を何度も持つので、ここで大半が落ちる。
                if len(pairs) != len(rows):
                    continue
                # ユーザー作成アルバムを1つも指さない表は、アルバム⇔写真ではない
                hits = len({a for a in a_vals if a in user_albums})
                if user_albums and hits == 0:
                    continue
                hint = (ac.upper().endswith("ALBUMS")) + (sc.upper().endswith("ASSETS"))
                cands.append(((hint, hits, len(rows)), name, ac, sc))
    if not cands:
        return None
    cands.sort(key=lambda c: c[0], reverse=True)
    best = cands[0]
    # 候補が拮抗している（名前の手がかりも無く、規模も近い）場合は推定を諦める。
    # 誤った表で全アルバムを作るより、止まって診断情報を出すほうが安全。
    if len(cands) > 1 and best[0][0] == 0 and cands[1][0][0] == 0:
        a, b = best[0][2], cands[1][0][2]
        if b and a / b < 3:
            log(t("   ⚠ アルバム⇔写真の対応表を一意に特定できませんでした。",
                  "   ⚠ Could not uniquely identify the album-asset table."))
            return None
    return best[1:]


def parse_albums(db_path):
    """戻り値: (albums: {表示パス: [DCIM相対パス,...]}, all_files: {DCIM相対パス})"""
    con = sqlite3.connect(db_path)  # ローカルコピーなのでRWで開きWALを適用
    try:
        cur = con.cursor()
        cols = lambda tbl: [r[1] for r in cur.execute(f'PRAGMA table_info("{tbl}")').fetchall()]
        tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        dump_path = os.path.join(app_dir(), "schema_dump.txt")

        if "ZASSET" not in tables or "ZGENERICALBUM" not in tables:
            dump_schema(cur, dump_path)
            sys.exit(t(f"写真/アルバムの表(ZASSET/ZGENERICALBUM)が見つかりません。\n   構造を {dump_path} に書き出しました。このファイルを送ってください。",
                       f"Photo/album tables (ZASSET/ZGENERICALBUM) not found.\n   Schema written to {dump_path}. Please share this file."))

        found = find_join_table(cur, cols)
        if not found:
            dump_schema(cur, dump_path)
            sys.exit(t(f"アルバム⇔写真の結合表を特定できませんでした。\n   構造を {dump_path} に書き出しました。このファイルを送ってください。",
                       f"Could not identify the album-asset join table.\n   Schema written to {dump_path}. Please share this file."))
        join_tbl, alb_col, ast_col = found

        acols, gcols = cols("ZASSET"), cols("ZGENERICALBUM")
        a_ok = "a.ZTRASHEDSTATE=0" if "ZTRASHEDSTATE" in acols else "1=1"
        g_ok = "g.ZTRASHEDSTATE=0" if "ZTRASHEDSTATE" in gcols else "1=1"
        has_parent = "ZPARENTFOLDER" in gcols

        has_uuid = "ZUUID" in gcols
        rows = cur.execute(
            f"SELECT Z_PK, ZTITLE, ZKIND{', ZPARENTFOLDER' if has_parent else ', NULL'}"
            f"{', ZUUID' if has_uuid else ', NULL'} "
            f"FROM ZGENERICALBUM g WHERE {g_ok}").fetchall()
        meta = {pk: (title, kind, parent) for pk, title, kind, parent, _u in rows}
        keys = {pk: (u or f"pk{pk}") for pk, _t, _k, _p, u in rows}

        # 各階層のフォルダ名を「その親の中で」一意に決める。
        # パス全体で衝突判定すると、親フォルダ側の重複（_cache_DCIM という名の
        # フォルダ、A:B と A?B、Folder と folder）を解決できないため。
        resolved = {}          # pk -> 確定した1階層ぶんの名前
        taken = {}             # (親pk, 正規化名) -> pk

        def resolve_name(pk, is_root_level):
            if pk in resolved:
                return resolved[pk]
            title, _kind, parent = meta[pk]
            base = safe(title) if title else "untitled"
            ckey = os.path.normcase(base).casefold()
            owner = taken.get((parent, ckey))
            # 出力先直下ではツール自身が使う名前も避ける
            clash = (owner is not None and owner != pk) or (is_root_level and ckey in INTERNAL)
            name = base
            if clash:
                suffix = str(keys.get(pk, "")).replace("-", "")[-6:] or str(pk)
                for i in range(1, 1000):
                    cand = f"{base}_{suffix}" if i == 1 else f"{base}_{suffix}_{i}"
                    ck = os.path.normcase(cand).casefold()
                    if taken.get((parent, ck)) in (None, pk) and not (is_root_level and ck in INTERNAL):
                        name, ckey = cand, ck
                        break
                log(t(f"   ⚠ 名前が重複するため『{base}』を『{name}』として保存します",
                      f"   ⚠ name clash: saving '{base}' as '{name}'"))
            taken.setdefault((parent, ckey), pk)
            resolved[pk] = name
            return name

        def chain(pk):
            """pk から根までの [フォルダ..., アルバム] を返す"""
            out_chain, cur_pk, guard = [], pk, 0
            while cur_pk in meta and guard < 32:
                title, kind, parent = meta[cur_pk]
                if cur_pk != pk and kind != KIND_FOLDER:
                    break
                if title:
                    out_chain.append(cur_pk)
                cur_pk, guard = parent, guard + 1
            return list(reversed(out_chain))

        def display_path(pk):
            ids = chain(pk)
            if not ids:
                return None
            parts = [resolve_name(node, i == 0) for i, node in enumerate(ids)]
            return os.path.join(*parts)

        q = f"""SELECT g.Z_PK, a.ZDIRECTORY, a.ZFILENAME
                FROM "{join_tbl}" j
                JOIN ZGENERICALBUM g ON g.Z_PK=j.{alb_col}
                JOIN ZASSET a ON a.Z_PK=j.{ast_col}
                WHERE g.ZKIND={KIND_USER_ALBUM} AND g.ZTITLE IS NOT NULL AND {a_ok} AND {g_ok}"""
        # Windowsで使えない文字を変換した結果、別々のアルバムが同じフォルダ名に
        # 潰れることがある（例: "A:B" と "A?B" がどちらも "A_B"）。
        # その場合は2つ目以降に固有IDの一部を付けて区別する。
        INTERNAL = internal_names()
        albums, album_keys, path_of_pk, used = {}, {}, {}, {}
        rows_q = cur.execute(q).fetchall()

        # フォルダ名は先に確定させる。同名アルバムがある場合にどちらが「素の名前」を
        # 取るかがDBの返す順に依存すると、実行のたびに入れ替わって
        # 中身がまるごと _削除済み に退避されてしまうため、UUID順で固定する。
        # 名前の確定は「UUID順」で行う。DBの返す順に依存すると、同名アルバムの
        # どちらが素の名前を取るかが実行のたびに入れ替わってしまうため。
        album_pks = {r[0] for r in rows_q}

        # 先に親フォルダを、フォルダ自身のUUID順で確定する。
        # 子アルバムのUUID順で決めてしまうと、アルバムを1つ足しただけで
        # 親フォルダ名（素の名前とサフィックス付き）が入れ替わってしまう。
        folder_pks = []
        for pk in album_pks:
            folder_pks += chain(pk)[:-1]
        by_depth = {}
        for fpk in set(folder_pks):
            by_depth.setdefault(len(chain(fpk)), []).append(fpk)
        for depth in sorted(by_depth):                       # 浅い階層から
            for fpk in sorted(by_depth[depth], key=lambda k: (str(keys.get(k, "")), k)):
                resolve_name(fpk, depth == 1)

        for pk in sorted(album_pks, key=lambda k: (str(keys.get(k, "")), k)):
            p = display_path(pk)
            if p:
                path_of_pk[pk] = p

        for pk, d, fn in rows_q:
            if not (d and fn):
                continue
            p = path_of_pk.get(pk)
            if p is None:
                continue
            albums.setdefault(p, []).append(f"{d}/{fn}")
            album_keys[p] = keys[pk]

        all_files = {f"{d}/{fn}" for d, fn in
                     cur.execute(f"SELECT ZDIRECTORY, ZFILENAME FROM ZASSET a WHERE {a_ok}").fetchall() if d and fn}

        # 撮影日時: ZDATECREATED は 2001-01-01 UTC からの秒。タイムゾーン補正があれば適用して現地時刻に。
        dates = {}
        if "ZDATECREATED" in acols:
            tz_join, tz_col = "", "NULL"
            if "ZADDITIONALASSETATTRIBUTES" in tables and \
               "ZTIMEZONEOFFSET" in cols("ZADDITIONALASSETATTRIBUTES") and \
               "ZASSET" in cols("ZADDITIONALASSETATTRIBUTES"):
                tz_join = "LEFT JOIN ZADDITIONALASSETATTRIBUTES x ON x.ZASSET=a.Z_PK"
                tz_col = "x.ZTIMEZONEOFFSET"
            for d, fn, created, tz in cur.execute(
                    f"SELECT a.ZDIRECTORY, a.ZFILENAME, a.ZDATECREATED, {tz_col} "
                    f"FROM ZASSET a {tz_join} WHERE {a_ok}").fetchall():
                if d and fn and created is not None:
                    dates[f"{d}/{fn}"] = APPLE_EPOCH + created + (tz or 0)
        # メディアタイプ判定に使う列（存在するものだけ使う）
        media, raw_combo = {}, {}
        want = [c for c in ("ZKIND", "ZKINDSUBTYPE", "ZPLAYBACKSTYLE", "ZDEPTHTYPE") if c in acols]
        sel = ", ".join(f"a.{c}" if c in want else "NULL" for c in ("ZKIND", "ZKINDSUBTYPE", "ZPLAYBACKSTYLE", "ZDEPTHTYPE"))
        cam_join, cam_col = "", "NULL"
        if "ZADDITIONALASSETATTRIBUTES" in tables and "ZCAMERACAPTUREDEVICE" in cols("ZADDITIONALASSETATTRIBUTES") \
           and "ZASSET" in cols("ZADDITIONALASSETATTRIBUTES"):
            cam_join = "LEFT JOIN ZADDITIONALASSETATTRIBUTES x ON x.ZASSET=a.Z_PK"
            cam_col = "x.ZCAMERACAPTUREDEVICE"
        for d, fn, kind, sub, pb, dep, cam in cur.execute(
                f"SELECT a.ZDIRECTORY, a.ZFILENAME, {sel}, {cam_col} FROM ZASSET a {cam_join} WHERE {a_ok}").fetchall():
            if d and fn:
                mtype = classify_media(kind, sub, pb, dep, cam, fn)
                media[f"{d}/{fn}"] = mtype
                key = (kind, sub, pb, dep, cam, os.path.splitext(fn)[1].upper())
                raw_combo[key] = raw_combo.get(key, 0) + 1
        return albums, all_files, dates, album_keys, media, raw_combo
    finally:
        con.close()


def classify_media(kind, subtype, playback, depth, camdev, filename):
    """ZASSET等の値からメディアタイプ名を返す。該当なしは None（＝ふつうの写真）。
    kind: 0=写真 1=動画 / subtype: 1=パノラマ 2=Live 10=スクショ 101=タイムラプス 102=スロー 103=画面録画
    playback: 2=アニメーション(GIF) 3=Live / depth: 1=ポートレート / camdev: 1=前面カメラ"""
    ext = os.path.splitext(filename or "")[1].lower()
    if kind == 1:
        if subtype == 103:
            return "画面録画"
        if subtype == 102:
            return "スローモーション"
        if subtype == 101:
            return "タイムラプス"
        return "ビデオ"
    if subtype == 10:
        return "スクリーンショット"
    if subtype == 1:
        return "パノラマ"
    if playback == 2 or ext == ".gif":
        return "アニメーション"
    if depth == 1:
        return "ポートレート"
    if subtype == 2 or playback == 3:
        return "Live Photos"
    if camdev == 1:
        return "セルフィー"
    return None


def internal_names():
    """出力先直下でツール自身が使う名前。ユーザーのアルバムがこの名前になると、
    キャッシュや状態ファイルを壊しうるので必ず別名にする。"""
    names = {CACHE_DIR, RENAME_TMP, STATE_FILE, STATE_FILE + ".tmp"}
    for key in ("unsorted", "removed", "media"):
        names |= {SPECIAL[key][0], SPECIAL[key][1]}
    names |= {"_取得失敗一覧.txt", "_failed_downloads.txt",
              "_iCloudにしか無い写真.txt", "_cloud_only_photos.txt",
              "_メディアタイプ診断.txt", "_media_type_diagnostics.txt",
              "schema_dump.txt", "_photos_db", "_settings.json"}
    return {os.path.normcase(n).casefold() for n in names}


def _special_whitelist():
    """special（_未分類・_メディアタイプ等のルートと種類名）としてstateに書かれてよい、
    既知の日本語/英語の名前だけを集めたホワイトリスト。
    改変されたstateファイルに任意の経路を書かれても、この集合に無ければ処理しない。"""
    names = set()
    for key in ("unsorted", "removed", "media", "nodate"):
        names |= {SPECIAL[key][0], SPECIAL[key][1]}
    for ja, en in MEDIA_NAMES.values():
        names |= {ja, en}
    return {os.path.normcase(n).casefold() for n in names}


RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def safe(name):
    """Windowsのフォルダ/ファイル名として安全な文字列にする"""
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    name = name.strip().rstrip(".") or "untitled"
    # CON, NUL, COM1 などは予約名で、そのままではフォルダを作れない
    if name.split(".", 1)[0].upper() in RESERVED:
        name = "_" + name
    return name


# ============================================================ パス境界（セキュリティ）
def safe_cache_path(cache, rel):
    """Photos.sqlite/AFC由来の相対パス(常に '/' 区切り)を、cache 配下の絶対パスに変換する。
    細工された ZDIRECTORY/ZFILENAME（例: "../secret.jpg"）や、AFCが返す不正な名前によって
    cache の外にあるファイルを参照できてしまうことを防ぐ。
    経路が cache の外に出る場合、または不正な形（'..'・空要素・バックスラッシュ混入）の場合は None。"""
    if not isinstance(rel, str) or not rel:
        return None
    if "\\" in rel:  # AFC/DB側は常にPOSIX形式('/')。バックスラッシュが混じるものは受け付けない
        return None
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    cache_abs = os.path.abspath(cache)
    candidate = os.path.abspath(os.path.join(cache_abs, *parts))
    try:
        if os.path.commonpath([cache_abs, candidate]) != cache_abs:
            return None
        # 文字列上は cache 配下でも、途中の階層がジャンクション/symlinkで
        # 外部を指していると実体は外に出る。realpath で辿った先も確認する。
        cache_real = os.path.realpath(cache_abs)
        candidate_real = os.path.realpath(candidate)
        if os.path.commonpath([cache_real, candidate_real]) != cache_real:
            return None
    except ValueError:  # Windowsで別ドライブなど、そもそも比較できない場合
        return None
    return candidate


def safe_under_root(root, rel):
    """_album_state.json のような「前回の保存内容」に由来する相対パスを、
    out（保存先）配下の絶対パスに変換する。
    state ファイルは前回の自分が書いたものだが、改変されたファイルや、
    他人から受け取ったバックアップフォルダの state を読む可能性があるため、
    そこに書かれた経路を無条件には信用しない。
    絶対パス・ドライブレター・root の外を指すものは None。"""
    if not isinstance(rel, str) or not rel:
        return None
    drive, _ = os.path.splitdrive(rel)
    if drive or os.path.isabs(rel):
        return None
    root_abs = os.path.abspath(root)
    candidate = os.path.abspath(os.path.join(root_abs, rel))
    try:
        if os.path.commonpath([root_abs, candidate]) != root_abs:
            return None
        root_real = os.path.realpath(root_abs)
        candidate_real = os.path.realpath(candidate)
        if os.path.commonpath([root_real, candidate_real]) != root_real:
            return None
    except ValueError:
        return None
    return candidate


def safe_managed_path(root, rel):
    """safe_under_root() に加えて、root より下の途中階層（と rel 自身）に
    symlink/NTFSジャンクションが無いことも確認する。
    root 自体がリンク経由なのは許可する（has_linkish_ancestor は stop=root で打ち切る）。

    safe_under_root() は「実体が root の外に出ないか」だけを見るため、
    out/AliasParent -> out/RealParent のように out 内部を指すリンクは通してしまう。
    このツールはリンクを自分では作らないので、out 配下のリンクは利用者が作ったもの。
    それを辿って書き込み・移動すると、ツール管理外のフォルダ（RealParent）の中身を
    触ってしまうため、ツールが書き込み・移動する経路はこちらを通す。"""
    candidate = safe_under_root(root, rel)
    if candidate is None:
        return None
    if has_linkish_ancestor(candidate, stop=os.path.abspath(root)):
        return None
    return candidate


# ============================================================ 再開可能ダウンロード
async def scan_remote(afc, path, cache=None, stats=None):
    """(リモートパス, サイズ) を再帰列挙。
    cache を渡した場合だけ、既に取得済みのファイルは iPhone への問い合わせを省く（高速モード）。
    既定では cache=None で呼ばれ、必ずリモートのサイズを確認する（安全側）。"""
    out = []
    _check_cancel()
    for name in await afc.listdir(path):
        # "." ".." "" に加え、'/' '\' を含む名前や制御文字も除外する。
        # 通常のAFCはこうした名前を返さないが、念のための境界チェック。
        if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
            continue
        full = f"{path}/{name}"
        if cache is not None and "." in name:      # 拡張子があればファイルとみなす
            local = safe_cache_path(cache, full)
            if local is not None and os.path.isfile(local):
                out.append((full, os.path.getsize(local)))
                if stats is not None:
                    stats["skipped"] = stats.get("skipped", 0) + 1
                continue
        st = await afc.stat(full)
        if stats is not None:
            stats["stat"] = stats.get("stat", 0) + 1
        if st.get("st_ifmt") == "S_IFDIR":
            out += await scan_remote(afc, full, cache, stats)
        else:
            out.append((full, int(st.get("st_size", 0))))
    return out


class LocalIOError(OSError):
    """PC側の問題（容量不足・権限・ロック）。リトライしても無駄なので即座に止める。
    OSError を継承し errno を引き継ぐので、呼び出し側は errno でも判別できる。"""

    def __init__(self, message, errno_=None):
        super().__init__(message)
        self.errno = errno_
        self.strerror = message


# 容量不足や読み取り専用ドライブは、待っても直らないので即座に止める
FATAL_ERRNOS = (errno.ENOSPC, errno.EROFS, errno.EDQUOT)
# Windowsではウイルス対策ソフトやインデックス作成がファイルを一時的に掴み、
# 権限エラー(EACCES)として現れる。これは待てば成功するので再試行する。
TRANSIENT_ERRNOS = (errno.EACCES, errno.EPERM, errno.EBUSY, errno.EMFILE)


def _fatal_local(e):
    return isinstance(e, OSError) and e.errno in FATAL_ERRNOS


def _transient_local(e):
    return isinstance(e, OSError) and e.errno in TRANSIENT_ERRNOS


async def _retry_local(fn, path, attempts=6):
    """PC側のファイル操作を、一時的なロック（ウイルス対策・インデックス作成）に耐えるよう再試行する。
    容量不足など回復不能なものは即座に止める。"""
    delay = 0.5
    for i in range(1, attempts + 1):
        try:
            return fn()
        except OSError as e:
            if _fatal_local(e):
                raise LocalIOError(_local_io_message(e, path), e.errno) from e
            if i == attempts and _transient_local(e):
                # 何度待っても駄目 → 原因と対処法を添えて止める
                raise LocalIOError(_local_io_message(e, path), e.errno) from e
            if not _transient_local(e):
                raise
            if i == 1:
                log(t(f"   ⏳ 保存先が一時的に使用中。待って再試行します: {os.path.basename(path)}",
                      f"   ⏳ destination busy, retrying: {os.path.basename(path)}"))
            await asyncio.sleep(delay)
            delay = min(delay * 2, 8)


async def download(afc, remote, local, size, retries=3):
    """1ファイル取得。中断・切断時は .part を残し、次回はその続きから再開する。"""
    if os.path.exists(local) and os.path.getsize(local) == size:
        return False  # 取得済み → スキップ（再開のキモ）
    d = os.path.dirname(local)
    if d not in _MADE_DIRS or not os.path.isdir(d):
        await _retry_local(lambda: os.makedirs(d, exist_ok=True), local)
        _MADE_DIRS.add(d)
    part = local + ".part"
    meta = part + ".size"
    # 途中再開のメタ情報は「大きいファイル」だけに書く。写真1枚ごとに書くと
    # 84,000回の余計なファイル作成/削除になり、これ自体が遅さの原因になる。
    use_meta = size >= RESUME_MIN
    for attempt in range(1, retries + 1):
        start = 0
        if os.path.exists(part):
            if use_meta:
                try:  # 前回の続きから。リモートのサイズが変わっていたら破棄して最初から
                    if int(open(meta).read().strip()) == size and os.path.getsize(part) <= size:
                        start = os.path.getsize(part)
                    else:
                        os.remove(part)
                except (OSError, ValueError):
                    start = 0
            else:
                try:
                    os.remove(part)  # 小さいファイルは取り直した方が速い
                except OSError:
                    pass
        h = None
        cancelled = None
        try:
            if use_meta and not start:
                with open(meta, "w") as f:
                    f.write(str(size))
            # 先にPC側のファイルを開く。iPhone側を開いてから待つと、
            # ウイルス対策のロックで待つ間ずっと端末のファイルハンドルを保持することになり、
            # 接続が不安定になる（保持したまま最大15秒待つ形になっていた）。
            fh = await _retry_local(lambda: open(part, "ab" if start else "wb"), part)
            try:
                h = await afc.fopen(remote, "r")
                if start:
                    await afc.fseek(h, start, os.SEEK_SET)
                done = start
                with fh as f:
                    while done < size:
                        try:
                            _check_cancel()
                        except Cancelled as c:
                            cancelled = c
                            break
                        chunk = await afc.fread(h, min(CHUNK, size - done))
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
            except OSError as e:
                try:
                    fh.close()
                except Exception:
                    pass
                if _fatal_local(e):
                    raise LocalIOError(_local_io_message(e, part), e.errno) from e
                raise   # 一時的なものは下の except で再試行される
            except BaseException:
                try:
                    fh.close()
                except Exception:
                    pass
                raise
            if cancelled is not None:
                raise cancelled  # .part は残す = 次回この続きから
            if os.path.getsize(part) != size:
                raise IOError(t("サイズ不一致", "size mismatch"))
            # 通信ではなくPC内の操作。一時的なロックは待って再試行し、
            # それでも駄目なら再取得はせずに止める。
            try:
                await _retry_local(lambda: os.replace(part, local), local)
            except LocalIOError:
                raise
            except OSError as e:
                raise LocalIOError(_local_io_message(e, local), getattr(e, "errno", None)) from e
            if use_meta:
                try:
                    os.remove(meta)
                except OSError:
                    pass
            return True
        except (Cancelled, LocalIOError):
            raise
        except Exception as e:
            if attempt == retries:
                raise
            log(t(f"   ⚠ 再試行 {attempt}/{retries}: {os.path.basename(remote)} ({e})",
                  f"   ⚠ retry {attempt}/{retries}: {os.path.basename(remote)} ({e})"))
            await asyncio.sleep(1)
        finally:
            if h is not None:
                try:
                    await afc.fclose(h)  # 切断時は失敗するが、本来の例外を隠してはいけない
                except Exception:
                    pass


def _local_io_message(e, path):
    if getattr(e, "errno", None) == errno.ENOSPC:
        return t(f"保存先の空き容量が足りません: {path}\n   空きを増やしてから、もう一度実行してください（続きから再開します）。",
                 f"Not enough free space on the destination: {path}\n   Free up space and run again (it resumes).")
    return t(
        f"保存先に書き込めません: {path}\n"
        f"   {e}\n"
        f"   よくある原因と対処:\n"
        f"   1) ウイルス対策ソフトがファイルを掴んでいる（最も多い）\n"
        f"      → 保存先フォルダを Windows セキュリティの『除外』に追加してください\n"
        f"        （設定 → プライバシーとセキュリティ → Windowsセキュリティ →\n"
        f"         ウイルスと脅威の防止 → 設定の管理 → 除外の追加または削除）\n"
        f"   2) 保存先ドライブの『内容にインデックスを付ける』が有効\n"
        f"      → ドライブのプロパティでオフにすると安定します\n"
        f"   3) エクスプローラーで保存先を開いたままにしている → 閉じてください\n"
        f"   ※ 取得済みのファイルは残っています。対処後にもう一度実行すれば続きから再開します。",
        f"Cannot write to the destination: {path}\n"
        f"   {e}\n"
        f"   Common causes:\n"
        f"   1) Antivirus is holding the file (most common)\n"
        f"      -> Add the destination folder to Windows Security exclusions\n"
        f"   2) Drive indexing is enabled -> turn it off in the drive properties\n"
        f"   3) The destination folder is open in Explorer -> close it\n"
        f"   Files already downloaded are kept; run again to resume.")


async def scan_dcim(afc, cache=None):
    """cache が None なら全ファイルのサイズをiPhoneに問い合わせる（安全）。
    cache を渡すと取得済みファイルの問い合わせを省く（高速だが、端末側で
    同名のまま中身が変わった場合に気づけない）。"""
    """DCIMの一覧だけ取る（(リモートパス, サイズ) のリスト）"""
    log(t("   iPhone内の写真一覧を取得中…（数分かかることがあります）", "   Listing photos on the iPhone… (this can take a few minutes)"))
    _progress("scan", 0, 0, 0, 0, "")
    stats = {}
    files = await scan_remote(afc, "DCIM", cache, stats)
    if stats.get("skipped"):
        log(t(f"   （取得済みの {stats['skipped']} ファイルは問い合わせを省略しました）",
              f"   (skipped device queries for {stats['skipped']} already-downloaded files)"))
    total = sum(s for _, s in files)
    log(t(f"   本体にある写真・動画 {len(files)} ファイル / 合計 {total/1024**3:.1f} GB", f"   {len(files)} photos/videos on device, {total/1024**3:.1f} GB total"))
    _event("counts", json.dumps({"bytes": total}))
    return files


async def _alive(afc):
    try:
        await afc.exists("DCIM")
        return True
    except Exception:
        return False


async def _wait_for_destination(path, timeout=1800, interval=5):
    """保存先（外付けドライブ等）が見えなくなった時、復帰を待つ。
    ここで待たずに1件ずつ失敗を積むと、ドライブが戻るまでの数分間に
    数千〜数万件を「取得できず」として処理してしまう（実際に9,997件発生した）。"""
    log("")
    log(t(f"   💾 保存先が見えなくなりました: {path}",
          f"   💾 The destination is no longer available: {path}"))
    log(t("      外付けドライブが省電力で切断された可能性があります。接続を確認してください"
          "（最大30分待ちます。中止も可）",
          "      The drive may have gone to sleep or been disconnected. Reconnect it "
          "(waiting up to 30 min; you can also Stop)"))
    _event("dest_lost", t(
        f"保存先が見えなくなりました。\n{path}\n\n"
        "外付けドライブの接続を確認してください。\n戻れば自動で続きから再開します。\n"
        "（最大30分待ちます。やめる場合は「■ 中止」）",
        f"The destination is no longer available.\n{path}\n\n"
        "Reconnect the drive; the backup resumes automatically.\n"
        "(Waiting up to 30 minutes. Press ■ Stop to give up.)"))
    t0 = time.time()
    while time.time() - t0 < timeout:
        for _ in range(interval * 2):
            _check_cancel()
            await asyncio.sleep(0.5)
        if os.path.isdir(path):
            _MADE_DIRS.clear()      # ドライブが戻ったのでフォルダの記憶を作り直す
            log("")
            log(t("   💾 保存先が戻りました。続きから再開します",
                  "   💾 The destination is back. Resuming"))
            _event("dest_back", t("保存先が戻りました。続きから再開します。",
                                  "The destination is back. Resuming."))
            return True
        el = int(time.time() - t0)
        log(t(f"\r   … 保存先の復帰を待っています {el//60}分{el%60:02d}秒",
              f"\r   … waiting for the destination {el//60}m{el%60:02d}s"), end="")
    raise LocalIOError(t(
        f"保存先が戻りませんでした: {path}\n"
        f"   外付けドライブの接続と、電源設定（ハードディスクの電源を切る）を確認してください。\n"
        f"   取得済みのファイルは残っています。もう一度実行すれば続きから再開します。",
        f"The destination did not come back: {path}\n"
        f"   Check the drive connection and the power setting that turns disks off.\n"
        f"   Files already downloaded are kept; run again to resume."))


async def _wait_reconnect(reconnect, timeout=600, interval=5, close_dead=None):
    """ケーブルが抜けた等。つなぎ直されるまで待って、新しいAFC接続を返す"""
    log("")
    log(t("   🔌 iPhoneとの接続が切れました。ケーブルをつなぎ直してください（最大10分待ちます。中止も可）", "   🔌 Lost connection to the iPhone. Please reconnect the cable (waiting up to 10 min; you can also Stop)"))
    _event("disconnected", t("iPhoneとの接続が切れました。\nケーブルをつなぎ直すと、自動で続きから再開します。\n（最大10分待ちます。やめる場合は「■ 中止」）", "Lost connection to the iPhone.\nReconnect the cable and the backup resumes automatically.\n(Waiting up to 10 minutes. Press ■ Stop to give up.)"))
    t0 = time.time()
    while time.time() - t0 < timeout:
        for _ in range(interval * 2):
            _check_cancel()
            await asyncio.sleep(0.5)
        try:
            afc = await reconnect()
            if await _alive(afc):
                log(t("   🔌 再接続しました。続きから再開します", "   🔌 Reconnected. Resuming"))
                _event("reconnected", t("再接続しました。続きから再開します。", "Reconnected. Resuming."))
                return afc
            if close_dead:                # 繋がったが使えなかった接続は溜めずに閉じる
                await close_dead()
        except Exception:
            pass
        log(t(f"\r   … 接続待ち {int(time.time()-t0)//60}分{int(time.time()-t0)%60:02d}秒", f"\r   … waiting for device {int(time.time()-t0)//60}m{int(time.time()-t0)%60:02d}s"), end="")
    raise ConnectionLost(t("10分以内に再接続されませんでした。つなぎ直してから、もう一度バックアップを始めてください（続きから再開します）", "No reconnection within 10 minutes. Reconnect and start the backup again (it will resume)."))


async def pull_dcim(afc, cache, files, out, reconnect=None, close_dead=None):
    """一覧に従ってダウンロード。1ファイルの失敗で全体を止めず、失敗一覧を out に書き出す。
    接続断は検知して再接続を待ち、同じファイルから再開する。中止は Cancelled で上がる。"""
    total = sum(s for _, s in files)
    done_b, got, failed, t0 = 0, 0, [], time.time()
    i = 0
    while i < len(files):
        remote, size = files[i]
        local = safe_cache_path(cache, remote)
        if local is None:
            # 通常のiPhoneデータでは起こらない（Photos.sqlite由来のパスが不正な形）。
            # 実体のあるファイルとして扱わず、失敗として記録して次へ進む。
            failed.append((remote, t("不正なパスのため取得できません", "invalid path, skipped")))
            log(t(f"   ✗ 不正なパスのため取得できません: {remote}", f"   ✗ invalid path, skipped: {remote}"))
            done_b += size
            i += 1
            continue
        try:
            if await download(afc, remote, local, size):
                got += 1
        except (Cancelled, LocalIOError):
            raise   # 中止と「PC側の致命的I/O」は1件の失敗として扱わず、即座に上へ返す
        except Exception as e:
            if not os.path.isdir(cache):
                # 保存先ドライブごと消えた。iPhoneのせいではないので先に判定する
                await _wait_for_destination(cache)
                continue        # 同じファイルからやり直す
            if not await _alive(afc):
                if reconnect is None:
                    raise ConnectionLost(str(e))
                afc = await _wait_reconnect(reconnect, close_dead=close_dead)
                continue  # 同じファイルをやり直す
            failed.append((remote, str(e)))
            log(t(f"   ✗ 取得できず（後で再試行できます）: {remote} — {e}", f"   ✗ could not fetch (will retry next run): {remote} — {e}"))
        done_b += size
        i += 1
        _progress("download", i, len(files), done_b, total, os.path.basename(remote))
        if i % 50 == 0 or i == len(files):
            el = time.time() - t0
            log(t(f"\r   {i}/{len(files)}  {done_b/1024**3:.1f}/{total/1024**3:.1f} GB  経過 {el/60:.0f}分", f"\r   {i}/{len(files)}  {done_b/1024**3:.1f}/{total/1024**3:.1f} GB  elapsed {el/60:.0f} min"), end="")
    log("")
    log(t(f"   新規ダウンロード {got} 件（残りは取得済みをスキップ）", f"   {got} new downloads (already-fetched files skipped)"))
    if not failed:
        _drop_stale_reports(out, ("_取得失敗一覧.txt", "_failed_downloads.txt"))
    if failed:
        p = os.path.join(out, t("_取得失敗一覧.txt", "_failed_downloads.txt"))
        with open(p, "w", encoding="utf-8") as f:
            f.write(t("このファイルは取得に失敗した写真の一覧です。もう一度バックアップを実行すると再試行されます。\n\n", "Files that could not be downloaded. Run the backup again to retry them.\n\n"))
            for r, e in failed:
                f.write(f"{r}\t{e}\n")
        log(t(f"   ⚠ {len(failed)} 件は取得できませんでした → 一覧: {p}（再実行で再試行されます）", f"   ⚠ {len(failed)} files could not be fetched → list: {p} (retried on next run)"))
    return len(failed)


def _drop_stale_reports(out, names):
    """今回0件なら、前回のレポートを残さない（古い内容を今回の結果と誤読させない）"""
    for n in names:
        p = os.path.join(out, n)
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def report_cloud_only(out, albums, all_files, remote_files):
    """DBにはあるが本体(DCIM)に実体が無い = 「iPhoneのストレージを最適化」でiCloud側にしか無い写真"""
    present = {r for r, _ in remote_files}
    cloud_only = sorted(all_files - present)
    if not cloud_only:
        log(t("   ☁ iCloudにしか無い写真: なし（すべて本体にあります）", "   ☁ Cloud-only photos: none (everything is on the device)"))
        _drop_stale_reports(out, ("_iCloudにしか無い写真.txt", "_cloud_only_photos.txt"))
        return 0
    where = {}
    for p, files in albums.items():
        for rel in files:
            where.setdefault(rel, []).append(p)
    path = os.path.join(out, t("_iCloudにしか無い写真.txt", "_cloud_only_photos.txt"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(t("以下の写真は iPhone 本体に実体が無く（iCloudに最適化済み）、このツールではまだ取得できていません。\n"
                  "iPhone の 設定 → 写真 → 「オリジナルをダウンロード」にして、Wi-Fi で時間を置いてから再実行してください。\n"
                  "本体の空き容量が足りない場合は、一部のアルバムだけ先に本体へ戻す運用も可能です。\n\n",
                  "These photos exist only in iCloud (optimized storage) and could not be fetched yet.\n"
                  "On the iPhone set Settings → Photos → \"Download and Keep Originals\", wait on Wi-Fi, then run again.\n\n"))
        for rel in cloud_only:
            f.write(f"{rel}\t{' / '.join(where.get(rel, [t('(アルバム未所属)', '(no album)')]))}\n")
    log(t(f"   ☁ iCloudにしか無い写真: {len(cloud_only)} 個 → 一覧: {path}", f"   ☁ Cloud-only photos: {len(cloud_only)} → list: {path}"))
    log(t("     （本体に無いので今回は取得できません。設定→写真→「オリジナルをダウンロード」後に再実行で取れます）", "     (Not on the device, so not fetched this time. Set Settings → Photos → \"Download and Keep Originals\", then run again.)"))
    return len(cloud_only)


# ============================================================ 振り分け
def has_linkish_ancestor(path, stop=None):
    """path 自身と、その親階層のどこかが symlink/NTFSジャンクションかどうか。
    stop（保存先ルート）が渡されればそこで打ち切る。渡されなければドライブ直下まで遡る。

    safe_managed_path() から stop=保存先ルート 付きで呼ばれ、out 配下の途中リンクを検出する。
    stop なしの呼び出しは、out_root を渡せない場合（外部からの直接利用・テスト）向けの保険。"""
    stop_key = os.path.normcase(os.path.abspath(stop)) if stop else None
    cur = os.path.abspath(path)
    while True:
        if stop_key is not None and os.path.normcase(cur) == stop_key:
            return False
        if is_linkish(cur):
            return True
        parent = os.path.dirname(cur)
        if parent == cur:          # ドライブ直下/ルートまで来た
            return False
        cur = parent


def place(src, dst_dir, tag, prefix="", out_root=None):
    """ハードリンク優先。同名で中身が違う場合は tag を付けて衝突回避。
    prefix(撮影日時)付きで置く際、同じ実体を指す旧名(prefix無し)があれば置き換える。"""
    # 出力先のアルバムフォルダの位置に、あらかじめ symlink/junction が仕込まれていると、
    # それを辿って保存先の外へ書き込んでしまう。dst_dir 自身だけでなく、
    # 親階層のどこかが symlink/junction のケースも塞ぐ必要がある。
    #
    # ここで「abspath と realpath が一致するか」で判定してはいけない。
    # 保存先そのものがジャンクション配下・割り当てネットワークドライブ・8.3短縮名だと
    # 正規の保存先まで realpath で別名に解決され、何も書けなくなる。
    # 判定すべきは「リンクを通ったか」ではなく「保存先ルートの外に出たか」なので、
    # out_root が分かるときは safe_managed_path() を使う。
    #   - safe_under_root(): 両側を realpath して commonpath 比較（外に出たか）
    #   - has_linkish_ancestor(stop=out_root): out 配下の途中リンク（out 内部を指すものも）を拒否
    # root 自体のリンクは stop で打ち切るので許可される。
    if out_root is not None:
        try:
            rel_dst = os.path.relpath(dst_dir, out_root)
        except ValueError:          # Windowsで別ドライブなど、そもそも比較できない
            rel_dst = None
        if rel_dst is None or safe_managed_path(out_root, rel_dst) is None:
            log(t(f"   ⚠ 保存先の外、またはシンボリックリンク/ジャンクション経由のため書き込みを拒否しました: {dst_dir}",
                  f"   ⚠ refused to write outside the destination or through a symlink/junction: {dst_dir}"))
            return None
    elif has_linkish_ancestor(dst_dir):
        # out_root が分からない場合は、外に出るかを判定できないので安全側に倒す
        log(t(f"   ⚠ シンボリックリンク/ジャンクション経由のため書き込みを拒否しました: {dst_dir}",
              f"   ⚠ refused to write through a symlink/junction: {dst_dir}"))
        return None
    # dst_dir 自身がリンクの場合は、行き先が保存先の内側でも従来どおり拒否する。
    # このツールはリンクを自分では作らないため、アルバムフォルダの位置に
    # リンクがあること自体が想定外の状態であり、v3.2.2 の挙動を維持する。
    if is_linkish(dst_dir):
        log(t(f"   ⚠ シンボリックリンク/ジャンクションのため書き込みを拒否しました: {dst_dir}",
              f"   ⚠ refused to write through a symlink/junction: {dst_dir}"))
        return None
    os.makedirs(dst_dir, exist_ok=True)
    base = os.path.basename(src)
    if prefix:
        legacy = os.path.join(dst_dir, base)
        if os.path.exists(legacy) and os.path.samefile(src, legacy):
            os.remove(legacy)
    dst = os.path.join(dst_dir, prefix + base)
    if os.path.exists(dst):
        if os.path.samefile(src, dst):
            return dst
        stem, ext = os.path.splitext(prefix + base)
        # 同名で別物 → tag付き、それも埋まっていれば連番で空きを探す（黙って取りこぼさない）
        dst = None
        for cand in [f"{stem}_{tag}{ext}"] + [f"{stem}_{tag}_{i}{ext}" for i in range(2, 100)]:
            p = os.path.join(dst_dir, cand)
            if not os.path.exists(p):
                dst = p
                break
            if os.path.samefile(src, p):
                return p
        if dst is None:
            return None
    try:
        os.link(src, dst)  # NTFS同一ドライブなら容量ゼロ
    except OSError:
        # ハードリンクが使えない場合のコピー。途中で失敗しても壊れたファイルを
        # 完成名で残さないよう、一時名で書いてから名前を変える。
        # 固定名(.copying)だと、利用者が元々同名のファイルを持っていた場合に
        # 上書き→削除してしまうため、毎回ランダムな名前にする。
        tmp = f"{dst}.{uuid.uuid4().hex}.copying"
        try:
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    return dst


def _pkey(path):
    """パス比較用の正規化。Windowsは大文字小文字を区別しないため、
    綴り違いで『置いていないファイル』と誤判定しないようにする。"""
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def place_asset(rel, cache, dst_dir, dates=None, date_prefix=True, placed=None, out_root=None):
    """戻り値: 実体が見つかれば True。placed(set) に置いたファイルの絶対パスを追加"""
    src = safe_cache_path(cache, rel)
    if src is None or not os.path.exists(src):
        return False
    tag = rel.split("/")[-2] if "/" in rel else "x"
    ts = (dates or {}).get(rel)
    prefix = ""
    if ts is not None:
        # 撮影日時(現地)を YYYYMMDD_HHMMSS_ で先頭に。ファイルの更新日時も撮影日時に合わせる
        prefix = time.strftime("%Y%m%d_%H%M%S_", time.gmtime(ts)) if date_prefix else ""
        try:
            os.utime(src, (ts, ts))  # ハードリンクは実体共有なので全リンクに反映
        except OSError:
            pass
    p = place(src, dst_dir, tag, prefix, out_root=out_root)
    if placed is not None and p:
        placed.add(_pkey(p))
    # Live Photos: 同名 .MOV があれば一緒に（同じ日付プレフィックスで）
    stem, ext = os.path.splitext(src)
    if ext.upper() in (".HEIC", ".JPG", ".JPEG"):
        for mov in (stem + ".MOV", stem + ".mov"):
            if os.path.exists(mov):
                if ts is not None:
                    try:
                        os.utime(mov, (ts, ts))
                    except OSError:
                        pass
                p = place(mov, dst_dir, tag, prefix, out_root=out_root)
                if placed is not None and p:
                    placed.add(_pkey(p))
                break
    # src(実体)は見つかっても、symlink拒否や衝突未解決で実際には
    # 何も配置できていないことがある。その場合はTrueを返さない
    # （呼び出し側はこの戻り値で missing 件数を数えているため）。
    return p is not None


# ============================================================ 前回状態との突き合わせ
def load_state(out):
    """前回の状態を読む。改変・破損したファイルでも後続処理が落ちないよう、
    最低限の型だけ確認する（内容そのものの正当性は各利用箇所の境界チェックに任せる）。"""
    p = os.path.join(out, STATE_FILE)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            if not isinstance(data.get("albums"), dict):
                data["albums"] = {}
            if not isinstance(data.get("special"), dict):
                data["special"] = {}
            else:
                # special の中身（types/media/unsorted/removed）も改変・破損の
                # 可能性があるため、利用側(reconcile_special)が素朴に
                # os.path.normcase()等へ渡しても落ちないよう、期待する型で
                # なければ握りつぶす（安全側のデフォルトに戻すだけで、
                # ファイルの移動先はここでは決めない＝実害のないDoS対策）。
                special = data["special"]
                types = special.get("types")
                special["types"] = (
                    {k: v for k, v in types.items() if isinstance(k, str) and isinstance(v, str)}
                    if isinstance(types, dict) else {}
                )
                for key in ("media", "unsorted", "removed"):
                    if key in special and not isinstance(special[key], str):
                        special.pop(key)
            return data
        except Exception:
            pass
    return {}


def save_state(out, album_keys, prev, dropped=()):
    """現在のアルバムで更新。iPhone側で消えたアルバムの記録は、退避(prune)するまで持ち越す"""
    merged = dict(prev.get("albums", {}))
    for k in dropped:
        merged.pop(k, None)
    merged.update({k: p for p, k in album_keys.items()})
    path = os.path.join(out, STATE_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:   # 途中で電源が落ちてもJSONが壊れないように
        json.dump({"albums": merged, "special": special_names()}, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def check_hardlink(cache, out):
    """本番前にハードリンクが本当に張れるか、小さなテストファイルで確認する。
    張れないと、同じ写真がアルバム/種類別フォルダの数だけ実体コピーされ、
    容量が2倍どころか3倍・4倍になりうるため、先に警告する。

    利用者の既存ファイルを絶対に消さないよう、名前は毎回ランダムにし、
    かつ「自分が新規作成できたもの」だけを後始末する。"""
    os.makedirs(cache, exist_ok=True)
    os.makedirs(out, exist_ok=True)
    token = f".iab_linktest_{uuid.uuid4().hex}"
    src = os.path.join(cache, token)
    dst = os.path.join(out, token + ".link")
    made_src = made_dst = False
    ok = False
    try:
        with open(src, "xb") as f:      # 既にあれば例外。上書きも削除もしない
            f.write(b"test")
        made_src = True
        os.link(src, dst)
        made_dst = True
        ok = os.path.samefile(src, dst)
    except OSError:
        ok = False
    finally:
        for path, mine in ((dst, made_dst), (src, made_src)):
            if mine:
                try:
                    os.remove(path)
                except OSError:
                    pass
    if ok:
        log(t("   ✅ ハードリンクが使えます（アルバム・種類別フォルダを作っても容量は増えません）",
              "   ✅ Hard links work (album and media-type folders cost no extra space)"))
        return True
    log(t("   ⚠ この保存先ではハードリンクが使えません。",
          "   ⚠ Hard links are not available on this destination."))
    log(t("     同じ写真がアルバムと種類別フォルダにそれぞれ実体コピーされるため、"
          "容量が数倍必要になります。",
          "     Each photo will be copied into every folder it belongs to, so it needs several times the space."))
    log(t("     保存先とキャッシュを同じドライブ（NTFS）にすると解決します。",
          "     Putting the destination and the cache on the same NTFS drive fixes this."))
    return False


def is_linkish(path):
    """symlink または（Windowsの）NTFSジャンクションかどうか。
    このツールはこれらを自分では作らないため、見つけても触らずスキップするのが最も安全。
    ディレクトリとして再帰すると、外部を指すリンク越しに保存先の外へ影響しうる。"""
    if os.path.islink(path):
        return True
    if hasattr(os.path, "isjunction") and os.path.isjunction(path):
        return True
    return False


def move_without_loss(src, dst):
    """src を dst へ移動。同名が既にある場合、同じ実体ならリンクを1本にまとめ、
    別物なら連番を付けて退避する（消さない）。戻り値は実際の移動先。"""
    if not os.path.exists(dst):
        shutil.move(src, dst)
        return dst
    if os.path.samefile(src, dst):
        os.remove(src)      # 同じ実体を指すリンク → 片方で十分
        return dst
    stem, ext = os.path.splitext(dst)
    for i in range(2, 10000):
        alt = f"{stem}_{i}{ext}"
        if not os.path.exists(alt):
            shutil.move(src, alt)
            return alt
    raise RuntimeError(t(f"同名ファイルの退避先を作れませんでした: {dst}",
                         f"could not find a free name for: {dst}"))


def _move_merge(src_dir, dst_dir):
    """フォルダを移動。移動先が既にあれば中身をマージ。
    symlink・NTFSジャンクションは辿らない（外部ディレクトリを指している可能性があり、
    再帰すると保存先の外にあるファイルを動かしてしまうため）。"""
    if is_linkish(src_dir):
        log(t(f"   ⚠ シンボリックリンク/ジャンクションのため処理をスキップしました: {src_dir}",
              f"   ⚠ skipped a symlink/junction: {src_dir}"))
        return
    if not os.path.exists(dst_dir):
        os.makedirs(os.path.dirname(dst_dir) or ".", exist_ok=True)
        shutil.move(src_dir, dst_dir)
        return
    for name in os.listdir(src_dir):
        s_, d_ = os.path.join(src_dir, name), os.path.join(dst_dir, name)
        if is_linkish(s_):
            log(t(f"   ⚠ シンボリックリンク/ジャンクションのため処理をスキップしました: {s_}",
                  f"   ⚠ skipped a symlink/junction: {s_}"))
            continue
        if os.path.isdir(s_):
            _move_merge(s_, d_)
        else:
            move_without_loss(s_, d_)
    try:
        os.rmdir(src_dir)
    except OSError:
        pass


def reconcile_special(out, prev):
    """前回と言語が違えば、特殊フォルダ（_未分類 ⇔ _Unsorted 等）を新しい名前へ移す。

    prev（_album_state.json）は前回の自分が書いたものだが、改変されている可能性や、
    他人から受け取ったバックアップフォルダの state を読む可能性があるため、
    そこに書かれた経路を無条件には信用しない。"""
    old = prev.get("special")
    if not old:
        return
    new = special_names()
    whitelist = _special_whitelist()
    old_media_raw = old.get("media", new["media"])
    old_media = old_media_raw if os.path.normcase(old_media_raw).casefold() in whitelist else new["media"]
    pairs = []
    # 先に種類フォルダ（旧ルート配下 → 新ルート配下）、その後にルート自体。逆だと旧ルートが消えて空振りする
    for k, nm in new["types"].items():
        o = old.get("types", {}).get(k)
        if o and o != nm and os.path.normcase(o).casefold() in whitelist:
            pairs.append((os.path.join(old_media, safe(o)), os.path.join(new["media"], safe(nm))))
    for k in ("unsorted", "removed", "media"):
        o = old.get(k)
        if o and os.path.normcase(o).casefold() in whitelist:
            pairs.append((o, new[k]))
    for o, n in pairs:
        if not o or o == n:
            continue
        src_abs = safe_managed_path(out, o)
        if src_abs is None:
            log(t(f"   ⚠ 前回の記録に不審な経路があるため無視しました: {o}",
                  f"   ⚠ ignored a suspicious path in the previous record: {o}"))
            continue
        if os.path.isdir(src_abs):
            dst_abs = safe_managed_path(out, n)
            if dst_abs is None:
                log(t(f"   ⚠ 移動先がシンボリックリンク/ジャンクション経由のためスキップしました: {n}",
                      f"   ⚠ skipped: the destination goes through a symlink/junction: {n}"))
                continue
            _move_merge(src_abs, dst_abs)
            log(t(f"   📝 フォルダ名を変更: {o} → {n}", f"   📝 Renamed folder: {o} → {n}"))


def reconcile_renames(out, album_keys, prev):
    """前回と同じアルバム(固有キー)で名前/場所が変わっていればフォルダを追従させる。

    A→B と B→A のような入れ替えや、Windowsでの大文字小文字だけの変更を安全に扱うため、
    いったん全部を一時フォルダへ退避してから最終名へ移す2段階方式にする。
    直接動かすと、退避前のフォルダに他方の中身が混ざったり、
    Windows上で同一フォルダ扱いになって唯一のリンクを消す危険がある。"""
    # prev（_album_state.json）に書かれた経路は、前回の自分が書いたものだが
    # 改変されている可能性があるため、out の外を指すものは使わない。
    prev_paths = prev.get("albums", {})
    moves = []
    for new_path, key in album_keys.items():
        old_path = prev_paths.get(key)
        if not old_path or old_path == new_path:
            continue
        src_abs = safe_managed_path(out, old_path)
        if src_abs is None:
            log(t(f"   ⚠ 前回の記録に不審な経路があるため無視しました: {old_path}",
                  f"   ⚠ ignored a suspicious path in the previous record: {old_path}"))
            continue
        if not os.path.isdir(src_abs):
            continue
        # 移動先（今回のアルバム名由来）も、途中にリンクがあれば動かさない。
        # 退避前に弾いておかないと、一時フォルダに取り残されてしまう。
        if safe_managed_path(out, new_path) is None:
            log(t(f"   ⚠ 移動先がシンボリックリンク/ジャンクション経由のため改名をスキップしました: {new_path}",
                  f"   ⚠ skipped rename: the destination goes through a symlink/junction: {new_path}"))
            continue
        moves.append((key, old_path, new_path, src_abs))
    if not moves:
        return

    tmp_root = os.path.join(out, RENAME_TMP)
    os.makedirs(tmp_root, exist_ok=True)
    staged = []
    try:
        # 第1段階: 対象を一時フォルダへ退避（この時点で衝突は起こらない）
        for key, old_path, new_path, src in moves:
            stage = os.path.join(tmp_root, safe(str(key)))
            if os.path.exists(stage):
                _move_merge(src, stage)
            else:
                os.makedirs(os.path.dirname(stage) or ".", exist_ok=True)
                shutil.move(src, stage)
            staged.append((stage, old_path, new_path))
        # 第2段階: 一時フォルダから最終名へ
        for stage, old_path, new_path in staged:
            dst = os.path.join(out, new_path)
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            if os.path.exists(dst):
                _move_merge(stage, dst)
            else:
                shutil.move(stage, dst)
            log(t(f"   📝 改名/移動: {old_path} → {new_path}",
                  f"   📝 renamed/moved: {old_path} → {new_path}"))
    finally:
        # 退避先が残っていたら中身を失わないよう戻す/掃除する
        if os.path.isdir(tmp_root):
            for name in os.listdir(tmp_root):
                leftover = os.path.join(tmp_root, name)
                log(t(f"   ⚠ 移動しきれなかったフォルダが {RENAME_TMP} に残っています: {name}",
                      f"   ⚠ a folder is left in {RENAME_TMP}: {name}"))
            try:
                os.rmdir(tmp_root)
            except OSError:
                pass


def prune(out, album_keys, prev, placed, managed_dirs):
    """iPhone側で消えた/外れたものを _削除済み に退避（削除はしない）"""
    removed_root = os.path.join(out, sp("removed"))
    # 呼び出し側が生のパスを渡すこともあるので、ここで必ず正規化してから比較する
    # （Windowsは大文字小文字を区別しないため、綴り違いでの誤退避を防ぐ）
    placed = {_pkey(p) for p in placed}
    n, dropped = 0, []
    # (a) アルバムごと消えた
    # prev の old_path は前回の自分が書いたものだが、改変されている可能性があるため、
    # out の外を指すものは使わない。
    cur_keys = set(album_keys.values())
    for key, old_path in prev.get("albums", {}).items():
        _check_cancel()
        if key in cur_keys:
            continue
        dropped.append(key)
        src_abs = safe_managed_path(out, old_path)
        if src_abs is None:
            log(t(f"   ⚠ 前回の記録に不審な経路があるため無視しました: {old_path}",
                  f"   ⚠ ignored a suspicious path in the previous record: {old_path}"))
            continue
        if os.path.isdir(src_abs):
            dst_abs = safe_managed_path(out, os.path.join(sp("removed"), old_path))
            if dst_abs is None:
                continue
            _move_merge(src_abs, dst_abs)
            log(t(f"   🗑 アルバム消滅 → {sp('removed')}\\{old_path}", f"   🗑 album gone → {sp('removed')}\\{old_path}"))
            n += 1
    # (b) アルバム内で外れた/消えた写真
    for d in managed_dirs:
        _check_cancel()
        # managed_dirs は呼び出し側（アルバム名などから組み立てたパス）由来で、
        # 途中の階層が symlink/junction で保存先の外を指している可能性がある。
        # d 自体や親をここで境界チェックしないと、listdir→move_without_loss が
        # 保存先外のファイルを動かしてしまう。
        try:
            rel_dir = os.path.relpath(d, out)
        except ValueError:
            continue
        # safe_managed_path は d 自身・途中階層のリンクも見る（out 内部を指すものも拒否）。
        # is_linkish(d) は d == out のとき（stop で打ち切られる）用に従来どおり残す。
        safe_d = safe_managed_path(out, rel_dir)
        if safe_d is None or is_linkish(d):
            log(t(f"   ⚠ 保存先外を指すフォルダのためスキップしました: {d}",
                  f"   ⚠ skipped a folder pointing outside the destination: {d}"))
            continue
        d = safe_d
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            _check_cancel()
            fp = os.path.join(d, name)
            if os.path.isfile(fp) and _pkey(fp) not in placed:
                dst_dir = os.path.join(removed_root, rel_dir)
                os.makedirs(dst_dir, exist_ok=True)
                move_without_loss(fp, os.path.join(dst_dir, name))
                n += 1
    if n:
        log(t(f"   🗑 {n} 件を {sp('removed')} に退避しました（削除はしていません）", f"   🗑 {n} items moved to {sp('removed')} (nothing deleted)"))
    return dropped


# ============================================================ main
def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="出力先フォルダ（例: D:\\iPhoneAlbums）")
    ap.add_argument("--cache", help="写真の実体置き場（省略時 出力先\\_cache_DCIM）※出力先と同じドライブに")
    ap.add_argument("--list", action="store_true", help="アルバム一覧だけ表示してダウンロードしない")
    ap.add_argument("--skip-pull", action="store_true", help="ダウンロードを飛ばして振り分けだけ")
    ap.add_argument("--refresh-db", action="store_true", help="写真データベースを取り直す（新しい写真を反映したい時）")
    ap.add_argument("--db", help="既に手元にある Photos.sqlite を使う（iPhone未接続でも解析可）")
    ap.add_argument("--no-date-prefix", action="store_true", help="ファイル名の先頭に撮影日時を付けない")
    ap.add_argument("--media-types", default="all",
                    help="メディアタイプ別フォルダを作る種類（カンマ区切り）。all=全部 / none=作らない")
    ap.add_argument("--fast-rescan", action="store_true",
                    help="取得済みファイルのサイズ確認を省いて再スキャンを高速化する"
                         "（端末側で同名のまま中身が変わった場合は検出できません）")
    ap.add_argument("--lang", default="ja", help="表示言語 / language: ja or en")
    ap.add_argument("--prune", action="store_true",
                    help="iPhone側で消した/アルバムから外した写真を _削除済み に退避する（既定: 何もしない）")
    return ap


async def _close_device(afc_cm, lockdown, conns):
    """AFC/lockdown を確実に閉じる（例外は握りつぶす。閉じ損ねると次回接続できなくなる）"""
    for cm, ld in [(afc_cm, lockdown)] + [(c, l) for l, c in conns]:
        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass
        if ld is not None:
            try:
                await ld.close()
            except Exception:
                pass
    conns.clear()


async def run(args):
    """GUI/CLI共通の本体。args は build_parser() の Namespace 互換なら何でもよい"""
    if not args.list and not args.out:
        raise SystemExit(t("出力先フォルダを指定してください。", "Please choose a destination folder."))
    set_language(getattr(args, "lang", "ja"))
    _MADE_DIRS.clear()   # 実行ごとにリセット（前回の記憶が実体と食い違うのを防ぐ）
    conns = []  # 再接続で増える (lockdown, afc_cm) を最後に閉じる
    target = {"udid": None}   # 最初に繋いだiPhone。再接続時はこの端末だけを狙う

    async def reconnect():
        # serial を省くと「最初に見つかった端末」が選ばれる。iPhoneが2台繋がっていると
        # 別の端末に切り替わり、同じキャッシュに混ざる危険があるのでUDIDで固定する。
        udid = target["udid"]
        ld = await (create_using_usbmux(serial=udid) if udid else create_using_usbmux())
        cm = None
        try:
            cm = AfcService(lockdown=ld)
            a = await cm.__aenter__()
        except Exception:
            try:
                await ld.close()   # conns に載る前に失敗した分は、ここで確実に閉じる
            except Exception:
                pass
            raise
        conns.append((ld, cm))
        return a

    async def close_dead():
        """再接続できたが実際には使えなかったセッションを閉じて、溜まらないようにする"""
        if conns:
            ld, cm = conns.pop()
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass
            try:
                await ld.close()
            except Exception:
                pass

    dbdir = os.path.join(app_dir(), "_photos_db")
    lockdown = None
    afc_cm = None
    failed_count = 0

    try:
        if args.db:
            log(t(f"[1/4] 手元の写真データベースを使用: {args.db}", f"[1/4] Using local Photos database: {args.db}"))
            db = args.db
            afc = None
        else:
            log(t("== iPhoneに接続中…（画面に『信頼』が出たらタップ）==", "== Connecting to iPhone… (tap \"Trust\" if asked) =="))
            lockdown = await connect()
            target["udid"] = getattr(lockdown, "udid", None)   # 再接続でこの端末に固定する
            log(t(f"   端末: {lockdown.display_name} / iOS {lockdown.product_version}", f"   Device: {lockdown.display_name} / iOS {lockdown.product_version}"))
            afc_cm = AfcService(lockdown=lockdown)
            afc = await afc_cm.__aenter__()

            async def with_reconnect(step):
                """接続断なら再接続を待って同じ処理をやり直す（DB取得は .part の続きから再開される）"""
                nonlocal afc
                while True:
                    try:
                        return await step(afc)
                    except Cancelled:
                        raise
                    except Exception:
                        if await _alive(afc):
                            raise
                        afc = await _wait_reconnect(reconnect, close_dead=close_dead)

            log(t(f"[1/4] 写真データベースを取得中… → {dbdir}", f"[1/4] Fetching the Photos database… → {dbdir}"))
            db = await with_reconnect(lambda a: pull_photos_db(a, dbdir, refresh=args.refresh_db))

        log(t("[2/4] アルバムを解析中…", "[2/4] Reading albums…"))
        albums, all_files, dates, album_keys, media, raw_combo = parse_albums(db)

        linked = set(f for v in albums.values() for f in v)
        unsorted = sorted(all_files - linked)
        log(t(f"   アルバム {len(albums)} 件 / 写真・動画 {len(all_files)} 個（どのアルバムにも無い: {len(unsorted)}）", f"   {len(albums)} albums / {len(all_files)} photos & videos (not in any album: {len(unsorted)})"))
        _event("counts", json.dumps({"items": len(all_files), "albums": len(albums)}))
        for p in sorted(albums):
            log(f"     📁 {p}  ({len(albums[p])})")
        counts = {}
        for mtype in media.values():
            if mtype:
                counts[mtype] = counts.get(mtype, 0) + 1
        log(t("   メディアタイプ（iPhoneの『メディアタイプ』画面の件数と見比べてください）", "   Media types (compare with the counts in the iPhone \"Media Types\" screen)"))
        for k in MEDIA_TYPES:
            log(f"     🏷 {media_name(k)}: {counts.get(k, 0)}")
        diag_dir = os.path.abspath(args.out) if args.out else app_dir()
        os.makedirs(diag_dir, exist_ok=True)
        diag = os.path.join(diag_dir, t("_メディアタイプ診断.txt", "_media_type_diagnostics.txt"))
        with open(diag, "w", encoding="utf-8") as f:
            f.write(t("種類判定の元データ（件数が iPhone と合わない時に、このファイルを共有してください）\n", "Raw values used for media-type detection (share this file if the counts differ from the iPhone)\n"))
            f.write("ZKIND\tZKINDSUBTYPE\tZPLAYBACKSTYLE\tZDEPTHTYPE\tZCAMERACAPTUREDEVICE\t" + t("拡張子\t件数\t判定", "ext\tcount\ttype") + "\n")
            for key, n in sorted(raw_combo.items(), key=lambda kv: -kv[1]):
                f.write("\t".join(str(k) for k in key) + f"\t{n}\t{classify_media(*key[:5], 'x' + key[5].lower()) or t('写真', 'Photo')}\n")
        if args.list:
            if getattr(args, "gui", False):
                log(t("\nアルバムの一覧はここまでです。内容に問題がなければ「3 バックアップを始める」を押してください。", "\nThat is the album list. If it looks right, press \"3 Start backup\"."))
            else:
                log(t("\n--list のためここで終了。問題なければ --out を付けて本実行してください。", "\nStopping here because of --list. Run again with --out to back up."))
            return

        out = os.path.abspath(args.out)
        cache = os.path.abspath(args.cache or os.path.join(out, "_cache_DCIM"))
        os.makedirs(cache, exist_ok=True)
        if os.path.splitdrive(out)[0].upper() != os.path.splitdrive(cache)[0].upper():
            log(t("   ⚠ 出力先とキャッシュが別ドライブ: ハードリンク不可のためコピーになり容量を余分に使います",
                  "   ⚠ Destination and cache are on different drives: hard links are impossible, files will be copied"))
        check_hardlink(cache, out)

        if args.skip_pull or afc is None:
            log(t("[3/4] ダウンロードを省略", "[3/4] Download skipped") + ("(--db)" if afc is None else "(--skip-pull)"))
        else:
            log(t(f"[3/4] 写真の実体をダウンロード中 → {cache}", f"[3/4] Downloading photo files → {cache}"))
            fast = cache if getattr(args, "fast_rescan", False) else None
            remote_files = await with_reconnect(lambda a: scan_dcim(a, fast))
            report_cloud_only(out, albums, all_files, remote_files)
            failed_count = await pull_dcim(afc, cache, remote_files, out, reconnect=reconnect, close_dead=close_dead)
        if afc is not None:
            await _close_device(afc_cm, lockdown, conns)   # 通信終了 → 先に閉じる
            afc_cm = lockdown = afc = None
            log(t("   📱 iPhoneとの通信は終わりました。ここから先はPC内の処理なので、ケーブルを外しても大丈夫です", "   📱 Finished talking to the iPhone. The rest runs on the PC, so you can unplug the cable"))
            _event("device_free", "")

        log(t(f"[4/4] アルバム別に振り分け中 → {out}", f"[4/4] Organizing into album folders → {out}"))
        prev = load_state(out)
        reconcile_special(out, prev)
        reconcile_renames(out, album_keys, prev)
        placed, missing = set(), 0
        total_links = sum(len(v) for v in albums.values())
        n_done = 0
        for p, files in albums.items():
            for rel in files:
                _check_cancel()
                if not place_asset(rel, cache, os.path.join(out, p), dates, not args.no_date_prefix, placed, out_root=out):
                    missing += 1
                n_done += 1
                if n_done % 200 == 0 or n_done == total_links:
                    _progress("organize", n_done, total_links, 0, 0, os.path.basename(rel))
                if n_done % 2000 == 0:
                    log(t(f"\r   アルバム振り分け {n_done}/{total_links}", f"\r   albums {n_done}/{total_links}"), end="")
        log(t(f"\r   アルバム振り分け {n_done}/{total_links}", f"\r   albums {n_done}/{total_links}"))
        unsorted_dirs = set()
        for rel in unsorted:
            _check_cancel()
            ts = dates.get(rel)
            sub = time.strftime("%Y/%Y-%m", time.gmtime(ts)) if ts else sp("nodate")
            d = os.path.join(out, sp("unsorted"), *sub.split("/"))
            unsorted_dirs.add(d)
            if not place_asset(rel, cache, d, dates, not args.no_date_prefix, placed, out_root=out):
                missing += 1
        # メディアタイプ別フォルダ（iPhoneと同じ分類。1つの写真は1種類のみ。ハードリンクなので容量は増えない）
        mt = getattr(args, "media_types", "all")
        if isinstance(mt, str):
            wanted = set(MEDIA_TYPES) if mt == "all" else set() if mt == "none" else {x.strip() for x in mt.split(",")}
        else:
            wanted = set(mt or [])
        media_dirs = set()
        if wanted:
            n_media = 0
            for rel in sorted(all_files):
                _check_cancel()
                mtype = media.get(rel)
                if not mtype or mtype not in wanted:
                    continue
                ts = dates.get(rel)
                sub = time.strftime("%Y/%Y-%m", time.gmtime(ts)) if ts else sp("nodate")
                d = os.path.join(out, sp("media"), safe(media_name(mtype)), *sub.split("/"))
                media_dirs.add(d)
                if place_asset(rel, cache, d, dates, not args.no_date_prefix, placed, out_root=out):
                    n_media += 1
            names = ", ".join(media_name(k) for k in MEDIA_TYPES if k in wanted)
            log(t(f"   🏷 メディアタイプ別: {n_media} 個を {sp('media')} に整理（{names}）",
                  f"   🏷 By media type: {n_media} items organized into {sp('media')} ({names})"))
        dropped = ()
        if getattr(args, "prune", False):
            # 古い版が _未分類 / _メディアタイプ の直下に置いたファイルも掃除対象にする
            # （現在は年\年-月 の下に置くため、直下に残っているものは過去の残骸）
            legacy_roots = [os.path.join(out, sp("unsorted")), os.path.join(out, sp("media"))]
            legacy_roots += [os.path.join(out, sp("media"), safe(media_name(k))) for k in MEDIA_TYPES]
            managed = ([os.path.join(out, p) for p in albums]
                       + sorted(unsorted_dirs) + sorted(media_dirs)
                       + [d for d in legacy_roots if os.path.isdir(d)])
            dropped = prune(out, album_keys, prev, placed, managed)
        save_state(out, album_keys, prev, dropped)
        log(t(f"\n✅ 完了  → {out}", f"\n✅ Done  → {out}"))
        if missing:
            if failed_count:
                # ダウンロード自体が失敗している場合、原因はiCloudではない
                log(t(f"   ※ {missing} 個がまだ揃っていません。うち {failed_count} 件はダウンロードに失敗しています"
                      f"（保存先の切断など）。",
                      f"   ※ {missing} files are missing; {failed_count} of them failed to download "
                      f"(e.g. the destination went offline)."))
                log(t("     原因を解消してから、もう一度実行してください。失敗した分だけ再取得します。",
                      "     Fix the cause and run again; only the failed files are fetched."))
            else:
                log(t(f"   ※ {missing} 個は実体が見つかりませんでした（iPhoneの『ストレージを最適化』で本体に無い可能性）。", f"   ※ {missing} files were not found on the device (probably iCloud-optimized)."))
                log(t("     設定→写真→『オリジナルをダウンロード』にして時間を置き、もう一度実行してください。", "     Set Settings → Photos → \"Download and Keep Originals\", wait, then run again."))
    finally:
        # 例外・中止・正常終了のいずれでも接続を必ず閉じる（閉じ損ねると次回つながらない）
        await _close_device(afc_cm, lockdown, conns)



async def main():
    ap = build_parser()
    args = ap.parse_args()
    if not args.list and not args.out:
        ap.error("--out を指定してください（例: --out D:\\iPhoneAlbums）")
    CANCEL.clear()
    await run(args)


if __name__ == "__main__":
    asyncio.run(main())
