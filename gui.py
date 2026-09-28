#!/usr/bin/env python3
"""
XYZETON Album Backup - GUI (customtkinter)
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

Project: https://github.com/xyzeton33/xyzeton-album-backup
Developed with assistance from Anthropic Claude.
gui.py ── XYZETON アルバムバックアップ GUI版（customtkinter）
エンジンは album_export.py。
"""
import argparse, asyncio, ctypes, json, os, queue, sys, threading, time, traceback
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk

import album_export as engine

VERSION = "3.3.1"
AUTHOR = "XYZETON"
REPO = "https://github.com/xyzeton33/xyzeton-album-backup"
AUTHOR = "XYZETON"
REPO_URL = "https://github.com/xyzeton33/xyzeton-album-backup"  # 公開時に実際のURLへ
SETTINGS = "_settings.json"

STR = {
 "title": ("XYZETON アルバムバックアップ", "XYZETON Album Backup"),
 "tagline": ("iPhoneのアルバム構成をそのまま、パソコンのフォルダに保存します。上から順に進めてください。",
             "Backs up your iPhone albums as folders on this PC, keeping the same structure. Work top to bottom."),
 "dest": ("保存先", "Save to"), "dest_ph": ("例: E:\\iPhoneAlbums", "e.g. E:\\iPhoneAlbums"), "browse": ("フォルダを選ぶ", "Choose folder…"),
 "step1": ("接続を確認", "Check connection"), "step2": ("アルバムを確認", "Review albums"), "step3": ("バックアップを始める", "Start backup"),
 "stop": ("中止", "Stop"), "stopping": ("中止しています…", "Stopping…"),
 "opt_date": ("ファイル名の先頭に撮影日時を付ける（名前順＝撮影順になる）", "Prefix file names with the capture date (name order = shooting order)"),
 "opt_skip": ("写真のダウンロードは飛ばし、フォルダ分けだけやり直す", "Skip downloading; only redo the folder organization"),
 "opt_refresh": ("アルバム情報を取り直す（iPhoneで写真やアルバムを変えた後に）", "Refresh album info (after changing photos/albums on the iPhone)"),
 "opt_prune": ("iPhoneで消した・アルバムから外した写真を「_削除済み」へ移す（削除はしない）", "Move photos deleted/removed on the iPhone into \"_Removed\" (never deletes)"),
 "opt_fast": ("2回目以降を高速化する（取得済みファイルの確認を省く。端末側で写真が差し替わった場合は気づけません）",
              "Speed up re-runs (skip verifying downloaded files; replaced photos are missed)"),
 "media_on": ("種類別フォルダも作る（アルバム未所属の動画などを探しやすく。容量は増えません）", "Also create folders by media type (find videos etc. not in any album; no extra space)"),
 "all": ("すべて", "All"), "none": ("なし", "None"),
 "copy_log": ("ログをコピー", "Copy log"), "idle": ("待機中", "Ready"),
 "intro": ("iPhoneをUSBでつなぎ、ロックを解除して「信頼」をタップしたら、「1 接続を確認」を押してください。\n",
           "Connect the iPhone by USB, unlock it, tap \"Trust\", then press \"1 Check connection\".\n"),
 "busy": ("処理中です。終わるまでお待ちください。", "Still working. Please wait until it finishes."),
 "need_dest": ("保存先フォルダを選んでください。", "Please choose a destination folder."),
 "confirm_run": ("写真の実体をすべてダウンロードします。\n数十〜数百GB・数時間かかることがあります。\n\n・PCがスリープしない設定にする\n・iPhoneはロックせず、つないだままにする\n\n開始しますか？",
                 "This downloads all photo files.\nIt can take hours and tens to hundreds of GB.\n\n• Prevent the PC from sleeping\n• Keep the iPhone unlocked and connected\n\nStart now?"),
 "confirm_stop": ("処理を中止しますか？\n\n取得済みのファイルは残り、次回は続きから再開できます。", "Stop now?\n\nDownloaded files are kept; the next run resumes from here."),
 "running": ("{}を実行中…", "{}…"), "finished": ("{}が終わりました", "{} finished"),
 "stopped_log": ("\n■ 中止しました。取得済みのファイルはそのまま残っています。\n  続きから再開するには、もう一度「3 バックアップを始める」を押してください。\n",
                 "\n■ Stopped. Downloaded files are kept.\n  Press \"3 Start backup\" again to resume.\n"),
 "stopped": ("中止しました（続きから再開できます）", "Stopped (you can resume)"),
 "lost": ("iPhoneとの接続が切れました（つなぎ直して3を押すと続きから）", "Lost connection (reconnect and press 3 to resume)"),
 "local_io": ("保存先に書き込めません（空き容量や権限を確認してください）", "Cannot write to the destination (check free space and permissions)"),
 "aborted": ("中断しました。上のメッセージを確認してください", "Aborted. See the message above"),
 "error": ("エラーで止まりました。「ログをコピー」で内容を共有してください", "Stopped with an error. Use \"Copy log\" to share it"),
 "stop_status": ("中止しています…（今のファイルの区切りで止まります）", "Stopping… (finishes the current file)"),
 "disc_title": ("接続が切れました", "Connection lost"),
 "disc_status": ("iPhoneとの接続が切れました。つなぎ直してください（自動で再開します）", "Lost connection to the iPhone. Reconnect the cable (resumes automatically)"),
 "reconn_status": ("再接続しました。続きから再開しています…", "Reconnected. Resuming…"),
 "free_status": ("iPhoneとの通信は終了。ケーブルを外しても大丈夫です（PC内の処理を続けています）", "Done with the iPhone. You can unplug it (still organizing files on the PC)"),
 "close": ("閉じる", "Close"), "yes": ("はい", "Yes"), "no": ("いいえ", "No"), "copied": ("ログをコピーしました", "Log copied"),
 "credit": (f"© 2026 {AUTHOR}  ·  GPL-3.0（無保証）  ·  AI支援で開発",
            f"© 2026 {AUTHOR}  ·  GPL-3.0 (no warranty)  ·  built with AI assistance"),
 "about": ("このツールについて", "About"),
 "about_body": (f"XYZETON アルバムバックアップ v{VERSION}\n作者: {AUTHOR}\n\n"
                f"ライセンス: GNU General Public License v3.0 以降\n"
                f"このプログラムは無保証です。詳細は同梱の LICENSE をご覧ください。\n"
                f"ソースコードは配布物に同梱、および下記で公開しています。\n{REPO}\n\n"
                f"利用ライブラリの表記は THIRD_PARTY_NOTICES.md をご覧ください。\n"
                f"開発には Anthropic Claude の支援を受けています。",
                f"XYZETON Album Backup v{VERSION}\nAuthor: {AUTHOR}\n\n"
                f"License: GNU General Public License v3.0 or later\n"
                f"This program comes with ABSOLUTELY NO WARRANTY. See the bundled LICENSE.\n"
                f"Source code is bundled with this release and published at:\n{REPO}\n\n"
                f"See THIRD_PARTY_NOTICES.md for third-party libraries.\n"
                f"Developed with assistance from Anthropic Claude."),
 "label_probe": ("接続の確認", "Connection check"), "label_list": ("アルバムの確認", "Album review"), "label_run": ("バックアップ", "Backup"),
 "probe_ok": ("✅ 接続できました  {} / iOS {}", "✅ Connected  {} / iOS {}"),
 "probe_db": ("✅ アルバム情報を読めます（{:,.0f} MB）", "✅ Album info is readable ({:,.0f} MB)"),
 "probe_next": ("次は「2 アルバムを確認」を押してください。初回はアルバム情報の取得に10〜20分かかります。", "Next, press \"2 Review albums\". The first time takes 10–20 minutes to fetch album info."),
 "probe_ng": ("⚠ アルバム情報にUSB経由で届きません。このiOSバージョンは未対応の可能性があります。", "⚠ Album info is not reachable over USB. This iOS version may be unsupported."),
 "dest_title": ("保存先フォルダを選ぶ", "Choose destination folder"),
 "device": ("iPhone", "iPhone"),
 "dev_none": ("未接続 — 「1 接続を確認」を押してください", "Not connected — press \"1 Check connection\""),
 "dev_ok": ("接続済み", "Connected"),
 "dev_items": ("写真・動画", "Photos & videos"),
 "dev_albums": ("アルバム", "Albums"),
 "settings": ("バックアップ設定", "Backup settings"),
 "show_log": ("詳細ログ", "Details"),
 "phase_db": ("アルバム情報を取得中", "Fetching album info"),
 "phase_scan": ("iPhone内の写真を調べています", "Listing photos on the iPhone"),
 "phase_download": ("写真をダウンロード中", "Downloading photos"),
 "phase_organize": ("フォルダに整理中", "Organizing into folders"),
 "elapsed": ("経過", "Elapsed"), "remain": ("残り", "Left"), "calculating": ("計算中", "estimating"),
 "reassure": ("取得済みのファイルは保存されています。中止しても次回は続きから再開できます。",
              "Files already downloaded are saved. You can stop and resume later."),
 "waiting_reconnect": ("再接続を待っています", "Waiting for the device"),
 "dest_lost_title": ("保存先が見えなくなりました", "Destination unavailable"),
 "dest_lost_status": ("保存先が見えなくなりました。ドライブの接続を確認してください（自動で再開します）",
                      "The destination is unavailable. Reconnect the drive (resumes automatically)"),
 "dest_back_status": ("保存先が戻りました。続きから再開しています…", "The destination is back. Resuming…"),
 "dest_waiting": ("保存先の復帰を待っています", "Waiting for the destination"),
 "last_backup": ("最後のバックアップ", "Last backup"),
 "items": ("項目", "items"),
 "never": ("まだ実行していません", "not yet"),
}
MEDIA_ORDER = ["ビデオ", "セルフィー", "Live Photos", "ポートレート", "パノラマ",
               "タイムラプス", "スローモーション", "スクリーンショット", "画面録画", "アニメーション"]


_OPTION_FLAGS = ("date_prefix", "refresh_db", "prune", "fast_rescan", "media_on")


def _normalize_settings(d):
    """_settings.json の中身を、GUIが前提とする型にそろえる。
    JSONとしては正しくても型が違う（"options" が配列など）と、起動時に落ちて
    設定ファイルを消すまで使えなくなるため。型が合わない項目だけ捨て、残りは保つ。"""
    if not isinstance(d, dict):
        return {}
    if d.get("lang") not in ("ja", "en"):
        d.pop("lang", None)
    if not isinstance(d.get("out", ""), str):
        d.pop("out", None)
    opts = d.get("options")
    if opts is not None:
        if not isinstance(opts, dict):
            d.pop("options", None)
        else:
            for k in _OPTION_FLAGS:
                if k in opts and not isinstance(opts[k], bool):
                    opts.pop(k)
            mt = opts.get("media_types")
            if mt is not None:
                if isinstance(mt, list):
                    opts["media_types"] = [x for x in mt if isinstance(x, str)]
                else:
                    opts.pop("media_types")
    last = d.get("last_backup")
    if last is not None:
        if not isinstance(last, dict):
            d.pop("last_backup", None)
        else:
            for k in ("when", "items"):
                if k in last and not isinstance(last[k], str):
                    last.pop(k)
    return d


def load_settings():
    try:
        with open(os.path.join(engine.app_dir(), SETTINGS), encoding="utf-8") as f:
            return _normalize_settings(json.load(f))
    except Exception:
        return {}


def save_settings(d):
    try:
        with open(os.path.join(engine.app_dir(), SETTINGS), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass

# ---- 高DPI対応（これが無いとWindowsで文字がぼやけて小さい）
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

# ---- デザイントークン
BG = "#F5F7F8"        # 画面の地
SURFACE = "#FFFFFF"   # カード
INK = "#182025"       # 本文
MUTED = "#69747C"     # 補足
LINE = "#DDE3E6"      # 罫線
ACCENT = "#287C82"    # アクセント（くすんだ青緑＝独自色）
ACCENT_HOVER = "#20666B"
FAINT = "#E8F0F0"     # アクセントの薄い面
OK = "#348267"
WARN = "#B77935"
STOP = "#B54B4B"
STOP_HOVER = "#9A3F3F"
FONT = "Yu Gothic UI"

ctk.set_appearance_mode("light")


class App(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=BG)
        self.geometry("880x820")
        self.minsize(820, 700)
        self.q = queue.Queue()
        self.worker = None
        self.notice = None
        self.settings = load_settings()
        self.lang = self.settings.get("lang", "ja")
        engine.set_language(self.lang)
        self.f_body = ctk.CTkFont(family=FONT, size=15)
        self.f_small = ctk.CTkFont(family=FONT, size=13)
        self.f_h1 = ctk.CTkFont(family=FONT, size=24, weight="bold")
        self.f_h2 = ctk.CTkFont(family=FONT, size=17, weight="bold")
        self.f_num = ctk.CTkFont(family=FONT, size=26, weight="bold")
        self.f_btn = ctk.CTkFont(family=FONT, size=16, weight="bold")
        self.f_log = ctk.CTkFont(family=FONT, size=13)
        # 状態（ウィジェットと独立に保持。言語切替で作り直すため）
        self.out_var = tk.StringVar(value=self.settings.get("out", ""))
        # 設定は次回起動時も保つ。ただし「ダウンロードを飛ばす」だけは毎回オフに戻す。
        # これが入ったままだと、写真を取得していないのにバックアップしたつもりになるため。
        saved = self.settings.get("options", {})
        self.date_prefix = tk.BooleanVar(value=saved.get("date_prefix", True))
        self.skip_pull = tk.BooleanVar(value=False)
        self.refresh_db = tk.BooleanVar(value=saved.get("refresh_db", False))
        self.prune = tk.BooleanVar(value=saved.get("prune", False))
        self.fast_rescan = tk.BooleanVar(value=saved.get("fast_rescan", False))
        self.media_on = tk.BooleanVar(value=saved.get("media_on", True))
        saved_types = saved.get("media_types")
        self.media_vars = {k: tk.BooleanVar(value=(k in saved_types) if saved_types is not None else True)
                           for k in engine.MEDIA_TYPES}
        self.status = tk.StringVar()
        self.log_text = ""
        self.step_done = {1: False, 2: False}
        self.device = {}
        self.settings_open = False
        self.log_open = False
        self.run_started = None
        self._build()
        engine.set_logger(self._log_from_worker)
        engine.set_event_handler(lambda kind, msg: self.q.put(("__event__", kind, msg)))
        engine.set_progress_handler(
            lambda ph, d, tt, db, tb, nm: self.q.put(("__prog__", ph, d, tt, db, tb, nm)))
        self.after(100, self._drain)
        self._log(self.S("intro"))

    def _save_options(self):
        """チェックの状態を次回起動時に復元できるよう保存する"""
        self.settings["options"] = {
            "date_prefix": self.date_prefix.get(),
            "refresh_db": self.refresh_db.get(),
            "prune": self.prune.get(),
            "fast_rescan": self.fast_rescan.get(),
            "media_on": self.media_on.get(),
            "media_types": [k for k, v in self.media_vars.items() if v.get()],
        }
        save_settings(self.settings)

    def S(self, key):
        ja, en = STR[key]
        return ja if self.lang == "ja" else en

    def _set_lang(self, value):
        lang = "ja" if value.startswith("日本") else "en"
        if lang == self.lang:
            return
        if self.worker and self.worker.is_alive():
            # 実行中に切り替えると、同じバックアップ内で _未分類 と _Unsorted が混ざる
            self._tell(self.S("busy"))
            self._rebuild_lang_switch()
            return
        self.lang = lang
        engine.set_language(lang)
        self.settings["lang"] = lang
        save_settings(self.settings)
        self.log_text = self.text.get("1.0", "end")
        for w in self.winfo_children():
            w.destroy()
        self._build()

    # ================================================================ UI
    def _rebuild_lang_switch(self):
        """切替を拒否したときに、見た目を現在の言語へ戻す"""
        try:
            self.lang_seg.set("日本語" if self.lang == "ja" else "English")
        except Exception:
            pass

    def _card(self, parent=None, **kw):
        return ctk.CTkFrame(parent or self.scroll, fg_color=SURFACE, corner_radius=14,
                            border_width=1, border_color=LINE, **kw)

    def _build(self):
        PAD = 22
        self.title(self.S("title"))

        # フッタ（常に画面下端に固定）
        foot = ctk.CTkFrame(self, fg_color="transparent", height=1)
        foot.pack(side="bottom", fill="x", padx=PAD + 6, pady=(8, 14))

        # 本文はすべてスクロール領域の中へ（設定を開いてもログに届くように）
        self.scroll = ctk.CTkScrollableFrame(self, fg_color=BG, corner_radius=0,
                                             scrollbar_button_color=LINE,
                                             scrollbar_button_hover_color=MUTED)
        self.scroll.pack(side="top", fill="both", expand=True)

        head = ctk.CTkFrame(self.scroll, fg_color="transparent", height=1)
        head.pack(fill="x", padx=PAD, pady=(10, 2))
        ctk.CTkLabel(head, text=self.S("title"), font=self.f_h1, text_color=INK).pack(side="left")
        ctk.CTkLabel(head, text=f"v{VERSION}", font=self.f_small, text_color=MUTED).pack(side="left", padx=(10, 0), pady=(8, 0))
        seg = ctk.CTkSegmentedButton(head, values=["日本語", "English"], font=self.f_small, height=30,
                                     selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
                                     unselected_color=SURFACE, unselected_hover_color=BG, text_color=INK,
                                     command=self._set_lang)
        seg.set("日本語" if self.lang == "ja" else "English")
        seg.pack(side="right")
        self.lang_seg = seg
        ctk.CTkLabel(self.scroll, text=self.S("tagline"), font=self.f_body, text_color=MUTED, anchor="w").pack(fill="x", padx=PAD)

        # ---- iPhone カード（接続後に中身が埋まる）
        dev = self._card()
        dev.pack(fill="x", padx=PAD, pady=(16, 0))
        drow = ctk.CTkFrame(dev, fg_color="transparent", height=1); drow.pack(fill="x", padx=18, pady=14)
        ctk.CTkLabel(drow, text="📱", font=ctk.CTkFont(family=FONT, size=26)).pack(side="left", padx=(0, 12))
        dtext = ctk.CTkFrame(drow, fg_color="transparent", height=1); dtext.pack(side="left", fill="x", expand=True)
        self.dev_name = ctk.CTkLabel(dtext, text=self.device.get("name", self.S("device")),
                                     font=self.f_h2, text_color=INK, anchor="w")
        self.dev_name.pack(fill="x")
        self.dev_sub = ctk.CTkLabel(dtext, text=self.device.get("sub", self.S("dev_none")),
                                    font=self.f_small, text_color=MUTED, anchor="w")
        self.dev_sub.pack(fill="x")
        self.dev_stats = ctk.CTkFrame(drow, fg_color="transparent", height=1); self.dev_stats.pack(side="right")
        self._render_stats()

        # ---- 保存先
        card = self._card(); card.pack(fill="x", padx=PAD, pady=(12, 0))
        row = ctk.CTkFrame(card, fg_color="transparent", height=1); row.pack(fill="x", padx=18, pady=14)
        ctk.CTkLabel(row, text=self.S("dest"), font=self.f_body, text_color=INK, width=64, anchor="w").pack(side="left")
        ctk.CTkEntry(row, textvariable=self.out_var, font=self.f_body, height=38, border_color=LINE,
                     placeholder_text=self.S("dest_ph")).pack(side="left", fill="x", expand=True, padx=(4, 10))
        ctk.CTkButton(row, text=self.S("browse"), font=self.f_body, height=38, width=140,
                      fg_color=SURFACE, hover_color=FAINT, text_color=ACCENT, border_width=1, border_color=ACCENT,
                      command=self._browse).pack(side="left")

        # ---- ステップ（順序を示すが、どれも押せる＝再実行できる）
        steps = ctk.CTkFrame(self.scroll, fg_color="transparent", height=1)
        steps.pack(fill="x", padx=PAD, pady=(14, 0))
        self.b_probe = self._step(steps, 1, self.S("step1"), self._do_probe)
        self.b_list = self._step(steps, 2, self.S("step2"), self._do_list)
        self.b_run = self._step(steps, 3, self.S("step3"), self._do_run)
        self.buttons = [self.b_probe, self.b_list, self.b_run]
        self._refresh_steps()

        # ---- 進捗パネル（実行中だけ中身が出る）
        self.pcard = self._card(); self.pcard.pack(fill="x", padx=PAD, pady=(12, 0))
        self.pbox = ctk.CTkFrame(self.pcard, fg_color="transparent", height=1); self.pbox.pack(fill="x", padx=18, pady=14)
        self.p_phase = ctk.CTkLabel(self.pbox, text="", font=self.f_h2, text_color=INK, anchor="w")
        self.p_phase.pack(fill="x")
        self.progress = ctk.CTkProgressBar(self.pbox, height=10, corner_radius=5,
                                           progress_color=ACCENT, fg_color=LINE, mode="determinate")
        self.progress.set(0)
        nums = ctk.CTkFrame(self.pbox, fg_color="transparent", height=1)
        self.nums = nums
        self.p_count = ctk.CTkLabel(nums, text="", font=self.f_body, text_color=INK, anchor="w"); self.p_count.pack(side="left")
        self.p_time = ctk.CTkLabel(nums, text="", font=self.f_body, text_color=MUTED, anchor="e"); self.p_time.pack(side="right")
        self.p_file = ctk.CTkLabel(self.pbox, text="", font=self.f_small, text_color=MUTED, anchor="w"); self.p_file.pack(fill="x", pady=(4, 0))
        self.p_note = ctk.CTkLabel(self.pbox, text=self.S("reassure"), font=self.f_small, text_color=MUTED, anchor="w")
        self._show_idle_panel()

        # ---- 設定（折りたたみ）
        self.set_card = self._card(); self.set_card.pack(fill="x", padx=PAD, pady=(12, 0))
        self.set_head = ctk.CTkButton(self.set_card, text="", font=self.f_body, anchor="w", height=44,
                                      fg_color="transparent", hover_color=FAINT, text_color=INK,
                                      command=self._toggle_settings)
        self.set_head.pack(fill="x", padx=8, pady=4)
        self.set_body = ctk.CTkFrame(self.set_card, fg_color="transparent", height=1)
        for key, var in [("opt_date", self.date_prefix), ("opt_skip", self.skip_pull),
                         ("opt_refresh", self.refresh_db), ("opt_prune", self.prune),
                         ("opt_fast", self.fast_rescan)]:
            ctk.CTkCheckBox(self.set_body, text=self.S(key), variable=var, font=self.f_body, text_color=INK,
                            fg_color=ACCENT, hover_color=ACCENT_HOVER, checkbox_width=20, checkbox_height=20,
                            command=self._save_options).pack(anchor="w", pady=3, padx=18)
        mrow = ctk.CTkFrame(self.set_body, fg_color="transparent", height=1); mrow.pack(fill="x", padx=18, pady=(10, 2))
        ctk.CTkCheckBox(mrow, text=self.S("media_on"), variable=self.media_on, font=self.f_body, text_color=INK,
                        fg_color=ACCENT, hover_color=ACCENT_HOVER, checkbox_width=20, checkbox_height=20,
                        command=self._toggle_media).pack(side="left")
        ctk.CTkButton(mrow, text=self.S("all"), width=56, height=26, font=self.f_small, fg_color="transparent",
                      hover_color=FAINT, text_color=MUTED, border_width=1, border_color=LINE,
                      command=lambda: self._set_media(True)).pack(side="right", padx=(6, 0))
        ctk.CTkButton(mrow, text=self.S("none"), width=56, height=26, font=self.f_small, fg_color="transparent",
                      hover_color=FAINT, text_color=MUTED, border_width=1, border_color=LINE,
                      command=lambda: self._set_media(False)).pack(side="right")
        grid = ctk.CTkFrame(self.set_body, fg_color="transparent", height=1); grid.pack(fill="x", padx=18, pady=(2, 14))
        self.media_boxes = []
        for i, k in enumerate([k for k in MEDIA_ORDER if k in engine.MEDIA_TYPES]):
            cb = ctk.CTkCheckBox(grid, text=engine.media_name(k), variable=self.media_vars[k], font=self.f_small,
                                 text_color=INK, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                 checkbox_width=18, checkbox_height=18, command=self._save_options)
            cb.grid(row=i // 5, column=i % 5, sticky="w", padx=(0, 12), pady=3)
            self.media_boxes.append(cb)
        for c in range(5):
            grid.columnconfigure(c, weight=1)
        self._toggle_media()
        self._render_settings_head()
        if self.settings_open:
            self.set_body.pack(fill="x")

        # ---- フッタの中身
        if not self.status.get():
            self.status.set(self.S("idle"))
        self.status_label = ctk.CTkLabel(foot, textvariable=self.status, font=self.f_small, text_color=MUTED, anchor="w")
        self.status_label.pack(side="left")
        ctk.CTkButton(foot, text=self.S("about"), font=self.f_small, height=28, width=104,
                      fg_color="transparent", hover_color=FAINT, text_color=MUTED, border_width=1,
                      border_color=LINE, command=self._show_about).pack(side="right")
        ctk.CTkButton(foot, text=self.S("copy_log"), font=self.f_small, height=28, width=104,
                      fg_color="transparent", hover_color=FAINT, text_color=MUTED, border_width=1,
                      border_color=LINE, command=self._copy_log).pack(side="right", padx=(0, 6))
        ctk.CTkLabel(foot, text=self.S("credit"), font=self.f_small, text_color=MUTED).pack(side="right", padx=(0, 14))

        # ---- ログ（折りたたみ。エラー時は自動で開く）
        self.log_card = self._card(); self.log_card.pack(fill="x", padx=PAD, pady=(12, 0))
        self.log_head = ctk.CTkButton(self.log_card, text="", font=self.f_body, anchor="w", height=40,
                                      fg_color="transparent", hover_color=FAINT, text_color=INK,
                                      command=self._toggle_log)
        self.log_head.pack(fill="x", padx=8, pady=4)
        self.text = ctk.CTkTextbox(self.log_card, font=self.f_log, text_color=INK, fg_color=BG,
                                   corner_radius=8, border_width=0, wrap="word", height=180)
        if self.log_text:
            self.text.insert("end", self.log_text)
            self.text.see("end")
        self.text.configure(state="disabled")
        self._render_log_head()
        if self.log_open:
            self.text.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkFrame(self.scroll, fg_color="transparent", height=8).pack(fill="x")

        if self.worker and self.worker.is_alive():
            self._enter_running_ui()

    def _scroll_to_bottom(self):
        try:
            self.scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    # ---- ステップ表示
    def _step(self, parent, num, label, cmd):
        b = ctk.CTkButton(parent, text=f"{num}   {label}", font=self.f_btn, height=52, corner_radius=10,
                          command=cmd)
        b.pack(side="left", fill="x", expand=True, padx=(0, 10))
        return b

    def _refresh_steps(self):
        """今やるべきステップだけを塗り、済んだものは control 感を落とす（でも押せる）"""
        current = 3 if self.step_done.get(2) else (2 if self.step_done.get(1) else 1)
        for i, b in enumerate(self.buttons, start=1):
            done = self.step_done.get(i, False)
            if i == current:
                b.configure(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#FFFFFF",
                            border_width=0, font=self.f_btn)
            elif done:
                b.configure(fg_color=FAINT, hover_color=LINE, text_color=ACCENT, border_width=0, font=self.f_body)
            else:
                b.configure(fg_color=SURFACE, hover_color=BG, text_color=MUTED,
                            border_width=1, border_color=LINE, font=self.f_body)

    def _render_stats(self):
        for w in self.dev_stats.winfo_children():
            w.destroy()
        for label, value in self.device.get("stats", []):
            col = ctk.CTkFrame(self.dev_stats, fg_color="transparent", height=1); col.pack(side="left", padx=(22, 0))
            ctk.CTkLabel(col, text=value, font=self.f_num, text_color=INK).pack()
            ctk.CTkLabel(col, text=label, font=self.f_small, text_color=MUTED).pack()

    # ---- 折りたたみ
    def _render_settings_head(self):
        self.set_head.configure(text=("▾  " if self.settings_open else "▸  ") + self.S("settings"))

    def _toggle_settings(self):
        self.settings_open = not self.settings_open
        self._render_settings_head()
        if self.settings_open:
            self.set_body.pack(fill="x")
        else:
            self.set_body.pack_forget()

    def _render_log_head(self):
        self.log_head.configure(text=("▾  " if self.log_open else "▸  ") + self.S("show_log"))

    def _toggle_log(self, force=None):
        self.log_open = (not self.log_open) if force is None else force
        self._render_log_head()
        if self.log_open:
            self.text.pack(fill="x", padx=12, pady=(0, 12))
            self.text.see("end")
            self.after(50, lambda: self._scroll_to_bottom())
        else:
            self.text.pack_forget()

    # ---- 進捗パネル
    def _show_idle_panel(self):
        for w in (self.progress, self.nums, self.p_file, self.p_note):
            w.pack_forget()
        self.p_phase.configure(text=self._last_backup_text(), font=self.f_small, text_color=MUTED)
        self.pbox.configure(height=1)

    def _last_backup_text(self):
        last = self.settings.get("last_backup")
        if not last:
            return f"{self.S('last_backup')}: {self.S('never')}"
        return f"{self.S('last_backup')}: {last.get('when','')}   {last.get('items','')} {self.S('items')}"

    def _enter_running_ui(self):
        self.p_phase.configure(font=self.f_h2, text_color=INK)
        self.progress.pack(fill="x", pady=(10, 8))
        self.nums.pack(fill="x")
        self.p_count.pack(side="left"); self.p_time.pack(side="right")
        self.p_file.pack(fill="x", pady=(4, 0))
        self.p_note.pack(fill="x", pady=(8, 0))
        self.b_run.configure(text=f"■   {self.S('stop')}", fg_color=STOP, hover_color=STOP_HOVER,
                             text_color="#FFFFFF", border_width=0, command=self._do_cancel)
        for b in (self.b_probe, self.b_list):
            b.configure(state="disabled")

    def _fmt_hm(self, sec):
        sec = int(max(sec, 0))
        h, m = divmod(sec // 60, 60)
        return f"{h}:{m:02d}" if h else f"{m}分" if self.lang == "ja" else f"{m} min"

    def _on_progress(self, phase, done, total, done_b, total_b, name):
        self.p_phase.configure(text=self.S(f"phase_{phase}") if f"phase_{phase}" in STR else "")
        if phase == "scan" or not total:
            if self.progress.cget("mode") != "indeterminate":
                self.progress.configure(mode="indeterminate"); self.progress.start()
            self.p_count.configure(text=""); self.p_time.configure(text=""); self.p_file.configure(text="")
            return
        if self.progress.cget("mode") != "determinate":
            self.progress.stop(); self.progress.configure(mode="determinate")
        frac = (done_b / total_b) if total_b else (done / total)
        self.progress.set(min(max(frac, 0), 1))
        if phase == "db":
            # DBは1ファイルなので件数は意味がない。容量と%だけ出す
            self.p_count.configure(text=f"{done_b/1024**3:.2f} / {total_b/1024**3:.2f} GB    {frac*100:.0f}%")
        elif total_b:
            self.p_count.configure(text=f"{done:,} / {total:,} {self.S('items')}"
                                        f"    {done_b/1024**3:.1f} / {total_b/1024**3:.1f} GB"
                                        f"    {frac*100:.0f}%")
        else:
            self.p_count.configure(text=f"{done:,} / {total:,} {self.S('items')}    {frac*100:.0f}%")
        el = time.time() - (self.run_started or time.time())
        txt = f"{self.S('elapsed')} {self._fmt_hm(el)}"
        # 残り時間は十分なサンプルが溜まってから（序盤の予測は外れるので出さない）
        if frac > 0.02 and el > 30:
            txt += f"    {self.S('remain')} {self._fmt_hm(el / frac - el)}"
        self.p_time.configure(text=txt)
        self.p_file.configure(text=name)

    def _browse(self):
        d = filedialog.askdirectory(title=self.S("dest_title"), parent=self)
        if d:
            self.out_var.set(os.path.normpath(d))
            self.settings["out"] = self.out_var.get()
            save_settings(self.settings)

    def _copy_log(self):
        self.clipboard_clear()
        self.clipboard_append(self.text.get("1.0", "end"))
        self.status.set(self.S("copied"))

    def _toggle_media(self):
        state = "normal" if self.media_on.get() else "disabled"
        for cb in self.media_boxes:
            cb.configure(state=state)
        self._save_options()

    def _set_media(self, value):
        for v in self.media_vars.values():
            v.set(value)
        self._save_options()

    def _open_out(self):
        out = self.out_var.get().strip()
        if out and os.path.isdir(out):
            try:
                if sys.platform == "win32":
                    os.startfile(out)
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", out])
            except Exception:
                pass

    # ================================================================ ログ / キュー
    def _log_from_worker(self, msg="", end="\n", flush=True):
        self.q.put(msg + end)

    def _drain(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple) and item[0] == "__prog__":
                    self._on_progress(*item[1:])
                elif isinstance(item, tuple) and item[0] == "__event__":
                    self._on_event(item[1], item[2])
                elif isinstance(item, tuple) and item[0] == "__done__":
                    self._finish(item[1])
                    if len(item) > 2 and item[2]:
                        self._open_out()
                else:
                    self._log(item)
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _log(self, s):
        self.text.configure(state="normal")
        if "\r" in s:
            s = s.split("\r")[-1]
            self.text.delete("end-1c linestart", "end-1c")
        self.text.insert("end", s)
        self.text.see("end")
        self.text.configure(state="disabled")
        if ("❌" in s or "⚠" in s or "🔌" in s) and not self.log_open:
            self._toggle_log(True)   # 問題が起きたらログを自動で開く

    # ================================================================ 実行
    def _start(self, coro_factory, label, step=None):
        if self.worker and self.worker.is_alive():
            self._tell(self.S("busy"))
            return
        engine.CANCEL.clear()
        self.run_started = time.time()
        self.running_step = step
        # 1・2・3 のどれを押しても、進捗と結果は詳細ログに出る。
        # 毎回「詳細ログ」を手で開くのは手間なので、実行開始時に自動で開く。
        self._toggle_log(True)
        self._enter_running_ui()
        self.status.set(self.S("running").format(label))
        self.status_label.configure(text_color=INK)
        self.p_phase.configure(text=self.S("running").format(label))
        self.progress.configure(mode="indeterminate"); self.progress.start()
        self._log(f"\n──── {label} ────\n")

        def target():
            try:
                asyncio.run(coro_factory())
                self.q.put(("__done__", self.S("finished").format(label), label == self.S("label_run")))
            except engine.Cancelled:
                self.q.put(self.S("stopped_log"))
                self.q.put(("__done__", self.S("stopped")))
            except engine.LocalIOError as e:
                self.q.put(f"\n💾 {e}\n")
                self.q.put(("__done__", self.S("local_io")))
            except engine.ConnectionLost as e:
                self.q.put(f"\n🔌 {e}\n")
                self.q.put(("__done__", self.S("lost")))
            except SystemExit as e:
                msg = str(e)
                self.q.put(("\n" + msg + "\n") if msg.startswith(("❌", "⚠")) else f"\n⚠ {msg}\n")
                self.q.put(("__done__", self.S("aborted")))
            except Exception as e:
                self.q.put(f"\n❌ {e}\n{traceback.format_exc()}\n")
                self.q.put(("__done__", self.S("error")))

        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()

    def _finish(self, msg):
        self._close_notice()
        self.progress.stop()
        ok = self.S("finished").format("").strip() in msg
        if ok and getattr(self, "running_step", None):
            self.step_done[self.running_step] = True
            if self.running_step == 3:
                self.settings["last_backup"] = {
                    "when": time.strftime("%Y-%m-%d %H:%M"),
                    "items": f"{getattr(self, 'last_total', 0):,}" if getattr(self, "last_total", 0) else "",
                }
                save_settings(self.settings)
        for b in self.buttons:
            b.configure(state="normal")
        self.b_run.configure(text=f"3   {self.S('step3')}", command=self._do_run)
        self._refresh_steps()
        self._show_idle_panel()
        self.status.set(msg)
        self.status_label.configure(text_color=OK if ok else WARN)
        self.bell()

    def _args(self, list_only):
        return argparse.Namespace(
            out=self.out_var.get().strip() or None, cache=None, list=list_only,
            skip_pull=self.skip_pull.get(), refresh_db=self.refresh_db.get(), db=None,
            no_date_prefix=not self.date_prefix.get(), prune=self.prune.get(), gui=True, lang=self.lang,
            fast_rescan=self.fast_rescan.get(),
            media_types=[k for k, v in self.media_vars.items() if v.get()] if self.media_on.get() else [],
        )

    def _do_probe(self):
        async def job():
            lockdown = await engine.connect()
            engine.log(self.S("probe_ok").format(lockdown.display_name, lockdown.product_version))
            self.device = {"name": lockdown.display_name,
                           "sub": f"iOS {lockdown.product_version}  ·  {self.S('dev_ok')}",
                           "stats": self.device.get("stats", [])}
            self.q.put(("__event__", "device_info", ""))
            ok = False
            try:
                async with engine.AfcService(lockdown=lockdown) as afc:
                    for c in engine.DB_CANDIDATES:
                        if await afc.exists(c):
                            size = int((await afc.stat(c))["st_size"])
                            engine.log(self.S("probe_db").format(size / 1024 ** 2))
                            ok = True
                            break
            finally:
                await lockdown.close()   # 途中で例外が出ても必ず閉じる
            engine.log(self.S("probe_next") if ok else self.S("probe_ng"))
        self._start(job, self.S("label_probe"), step=1)

    def _do_list(self):
        args = self._args(True)   # 設定値はここ（メインスレッド）で確定させる
        self._start(lambda: engine.run(args), self.S("label_list"), step=2)

    def _do_run(self):
        if not self.out_var.get().strip():
            self._tell(self.S("need_dest"))
            return
        if not self.skip_pull.get():
            if not self._ask_yes_no(self.S("confirm_run")):
                return
        self.settings["out"] = self.out_var.get().strip()
        save_settings(self.settings)
        # tkinterの変数は別スレッドから読んではいけない。開始時点の値を固定して渡す。
        args = self._args(False)
        self._start(lambda: engine.run(args), self.S("label_run"), step=3)

    def _do_cancel(self):
        if not self._ask_yes_no(self.S("confirm_stop")):
            return
        self.b_run.configure(state="disabled", text=f"■   {self.S('stopping')}")
        self.status.set(self.S("stop_status"))
        engine.request_cancel()

    # ================================================================ 接続イベント
    def _on_event(self, kind, msg):
        if kind == "device_info":
            self.dev_name.configure(text=self.device.get("name", self.S("device")))
            self.dev_sub.configure(text=self.device.get("sub", self.S("dev_none")))
            self._render_stats()
        elif kind == "counts":
            try:
                d = json.loads(msg)
            except Exception:
                d = {}
            self.dev_counts = {**getattr(self, "dev_counts", {}), **d}
            c = self.dev_counts
            stats = []
            if c.get("items"):
                stats.append((self.S("dev_items"), f"{c['items']:,}"))
                self.last_total = c["items"]
            if c.get("albums"):
                stats.append((self.S("dev_albums"), f"{c['albums']:,}"))
            if c.get("bytes"):
                stats.append(("GB", f"{c['bytes']/1024**3:.1f}"))
            self.device["stats"] = stats
            self._render_stats()
        elif kind == "dest_lost":
            self.bell()
            self.status.set(self.S("dest_lost_status"))
            self.status_label.configure(text_color=WARN)
            self.p_phase.configure(text=self.S("dest_waiting"), text_color=WARN)
            self._show_notice(self.S("dest_lost_title"), msg)
        elif kind == "dest_back":
            self._close_notice()
            self.status.set(self.S("dest_back_status"))
            self.status_label.configure(text_color=INK)
            self.p_phase.configure(text_color=INK)
        elif kind == "disconnected":
            self.bell()
            self.status.set(self.S("disc_status"))
            self.status_label.configure(text_color=WARN)
            self.p_phase.configure(text=self.S("waiting_reconnect"), text_color=WARN)
            self._show_notice(self.S("disc_title"), msg)
        elif kind == "reconnected":
            self._close_notice()
            self.status.set(self.S("reconn_status"))
            self.status_label.configure(text_color=INK)
            self.p_phase.configure(text_color=INK)
        elif kind == "device_free":
            self.status.set(self.S("free_status"))

    def _show_about(self):
        self._tell(self.S("about_body"), title=self.S("about"), icon="ℹ")

    # ================================================================ ダイアログ（必ず親ウィンドウの中央に出す）
    def _center_on_self(self, win):
        """親ウィンドウの中央へ。マルチモニタでは座標が負になることもあるので丸めない。"""
        win.update_idletasks()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        pw, ph = self.winfo_width(), self.winfo_height()
        ww, wh = win.winfo_width(), win.winfo_height()
        x = px + (pw - ww) // 2
        y = py + (ph - wh) // 3      # やや上の方が視線に入りやすい
        win.geometry(f"+{x}+{y}")

    def _dialog(self, title, msg, buttons, icon="?"):
        """親ウィンドウ中央に出るモーダルダイアログ。buttons は [(表示文字, 戻り値), ...]。
        tkinterの messagebox は Windows では親の中央に出る保証がなく、
        別モニタに飛んで気づけないことがあるため自前で用意している。"""
        result = {"value": buttons[-1][1]}
        w = ctk.CTkToplevel(self, fg_color=SURFACE)
        w.title(title)
        w.resizable(False, False)
        w.transient(self)
        ctk.CTkLabel(w, text=icon, font=ctk.CTkFont(family=FONT, size=30)).pack(pady=(20, 2))
        ctk.CTkLabel(w, text=title, font=self.f_h2, text_color=INK).pack()
        ctk.CTkLabel(w, text=msg, font=self.f_body, text_color=INK, justify="left").pack(padx=30, pady=14)
        row = ctk.CTkFrame(w, fg_color="transparent", height=1)
        row.pack(pady=(0, 20))

        def choose(v):
            result["value"] = v
            w.grab_release()
            w.destroy()

        for i, (label, value) in enumerate(buttons):
            primary = (i == 0 and len(buttons) > 1)
            ctk.CTkButton(row, text=label, font=self.f_body, width=130, height=36,
                          fg_color=ACCENT if primary else SURFACE,
                          hover_color=ACCENT_HOVER if primary else FAINT,
                          text_color="#FFFFFF" if primary else INK,
                          border_width=0 if primary else 1, border_color=LINE,
                          command=lambda v=value: choose(v)).pack(side="left", padx=6)
        w.protocol("WM_DELETE_WINDOW", lambda: choose(buttons[-1][1]))
        self._center_on_self(w)
        w.lift()
        w.attributes("-topmost", True)
        w.after(200, lambda: w.attributes("-topmost", False))
        w.grab_set()          # 親を触れなくする（＝必ず気づく位置に出す必要がある）
        w.focus_force()
        self.wait_window(w)
        return result["value"]

    def _ask_yes_no(self, msg):
        return self._dialog(self.S("title"), msg,
                            [(self.S("yes"), True), (self.S("no"), False)], icon="?")

    def _tell(self, msg, title=None, icon="!"):
        self._dialog(title or self.S("title"), msg, [(self.S("close"), None)], icon=icon)

    def _show_notice(self, title, msg):
        self._close_notice()
        w = ctk.CTkToplevel(self, fg_color=SURFACE)
        w.title(title); w.resizable(False, False); w.transient(self)
        ctk.CTkLabel(w, text="🔌", font=ctk.CTkFont(family=FONT, size=34)).pack(pady=(18, 4))
        ctk.CTkLabel(w, text=title, font=self.f_h2, text_color=INK).pack()
        ctk.CTkLabel(w, text=msg, font=self.f_body, text_color=INK, justify="left").pack(padx=28, pady=12)
        ctk.CTkButton(w, text=self.S("close"), font=self.f_body, width=120, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self._close_notice).pack(pady=(0, 18))
        w.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - w.winfo_width()) // 2
        y = self.winfo_y() + (self.winfo_height() - w.winfo_height()) // 2
        w.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        w.lift(); w.attributes("-topmost", True)
        self.notice = w

    def _close_notice(self):
        if self.notice is not None:
            try:
                self.notice.destroy()
            except Exception:
                pass
            self.notice = None


if __name__ == "__main__":
    App().mainloop()
