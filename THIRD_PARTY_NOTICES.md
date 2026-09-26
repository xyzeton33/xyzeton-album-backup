# サードパーティ・ライセンス表記

iPhone Album Backup — Copyright (C) 2026 XYZETON

本ソフトウェア (iPhone Album Backup) の著作権: Copyright (C) 2026 XYZETON

本ソフトウェアは GNU General Public License v3.0 (GPL-3.0-or-later) の下で公開されています。
全文は LICENSE ファイルを参照してください。ソースコードは配布物に同梱、および GitHub で公開しています。

本ソフトウェアは以下のオープンソースソフトウェアを利用しています。

| ライブラリ | ライセンス | 用途 |
|---|---|---|
| pymobiledevice3 | GPL-3.0-or-later | iPhoneとのUSB通信（AFC / lockdown） |
| cryptography | Apache-2.0 / BSD-3-Clause | 通信の暗号化 |
| construct | MIT | バイナリプロトコルの解析 |
| pyimg4 | MIT | pymobiledevice3 の依存 |
| lzfse | MIT | pymobiledevice3 の依存 |
| pylzss | LGPL-3.0 | pymobiledevice3 の依存 |
| developer-disk-image | GPL-3.0-or-later | pymobiledevice3 の依存 |
| ipsw-parser | GPL | pymobiledevice3 の依存 |
| tqdm | MPL-2.0 / MIT | pymobiledevice3 の依存 |
| customtkinter | CC0-1.0 | GUI の見た目（モダンなウィジェット） |
| Python / tkinter | PSF License | 実行環境 / GUI 基盤 |
| PyInstaller | GPL-2.0 with bootloader exception | exe 化 |

各ライブラリの詳細なライセンス文は、配布物内 `_internal\<ライブラリ名>-<版>.dist-info\` に同梱されています。

## 免責
本ソフトウェアは Apple 非公式の手段（写真アプリの内部データベースを USB 経由で読み取る）に依存しています。
iOS のアップデートにより予告なく動作しなくなる可能性があります。無保証・自己責任でご利用ください。

## 開発について
企画・画面設計・実機検証は作者（XYZETON）が、プログラムの実装は Anthropic Claude が担当しました。
