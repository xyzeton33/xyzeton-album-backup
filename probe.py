#!/usr/bin/env python3
"""
XYZETON Album Backup - connection / capability check
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
probe.py ── 最初に実行する「動作チェック」。ダウンロードは一切しません（約1分）。
  ・PCがiPhoneと会話できるか
  ・写真のアルバム情報(Photos.sqlite)を読める世代かどうか
を判定して、次に何をすればいいかを表示します。
"""
import asyncio, sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
try:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.afc import AfcService
except ImportError:
    sys.exit("pymobiledevice3 が入っていません。先に  pip install pymobiledevice3  を実行してください。")

CANDIDATES = ["PhotoData/Photos.sqlite", "PhotoData/PhotoData/Photos.sqlite"]


async def main():
    print("== iPhoneに接続中…（iPhoneに『このコンピュータを信頼』が出たらタップ）==")
    try:
        lockdown = await create_using_usbmux()
    except Exception as e:
        import album_export
        sys.exit(album_export.connection_help(e))
    print(f"✅ 接続OK  端末: {lockdown.display_name} / iOS {lockdown.product_version}")

    found = None
    try:
        async with AfcService(lockdown=lockdown) as afc:
            print(f"   写真の実体フォルダ(DCIM): {'見える' if await afc.exists('DCIM') else '見えない'}")
            for c in CANDIDATES:
                try:
                    if await afc.exists(c):
                        size = int((await afc.stat(c)).get("st_size", 0))
                        print(f"   アルバム情報(Photos.sqlite): 見える  ({size/1_048_576:.1f} MB)")
                        found = c
                        break
                except Exception as e:
                    print(f"   {c}: エラー {e}")
    finally:
        await lockdown.close()   # 途中で例外が出ても必ず閉じる

    print("\n=== 判定 ===")
    if found:
        print("✅ このiPhoneは高速ルートで行けます。")
        print("   次のコマンド:  python album_export.py --list")
    else:
        print("⚠️ アルバム情報にUSB経由で届きませんでした（iOS側で閉じられている世代）。")
        print("   この場合は『フルバックアップ経由』の別ルートが必要です。")
        print("   この画面の内容をそのまま貼って相談してください。")


if __name__ == "__main__":
    asyncio.run(main())
