# セキュリティ上の問題の報告 / Reporting security issues

XYZETON Album Backup は個人開発のツールです。
保存先フォルダの外へ書き込める、写真が意図せず移動・上書きされる、といった
**セキュリティ上の問題**を見つけた場合は、公開の Issue には書かず、次の方法で知らせてください。

エラーで止まる・接続できないなど、**セキュリティ以外の不具合**は、
通常の [Issue](https://github.com/xyzeton33/xyzeton-album-backup/issues/new/choose) の「不具合の報告」からお願いします。

## 報告の方法

GitHub の非公開報告機能を使ってください。

1. https://github.com/xyzeton33/xyzeton-album-backup/security を開く
2. 「Report a vulnerability」を押す
3. 下の「書いてほしいこと」を記入して送信

GitHub のフォームは英語ですが、日本語で書いて構いません。

GitHub 上では、内容は作者とあなたにしか見えません（作者が内容を整理するときの扱いは、下の「報告内容の扱い」をご覧ください）。
修正版を公開するまでは、内容をSNSや公開Issueに書かないようお願いします。

## 書いてほしいこと

再現できないと直せないため、**手順より先に「条件」**を書いてください。

- 使っているバージョン（画面上部のタイトル横、または右下の「このツールについて」で確認できます）
- Windows のバージョン
- 問題が起きる条件（例: 保存先が外付けドライブ／ネットワークドライブ、保存先の中にジャンクションがある、など）
- 再現手順（できるだけ短く。番号付きで）
- 実際に起きたこと（何が、どこへ、移動・上書き・削除されたか）

## ログを貼る前に

「ログをコピー」で取れるログには、次の情報が含まれることがあります。
貼る前に、見られて困る部分を `***` などに置き換えてください。

- Windows のユーザー名（`C:\Users\あなたの名前\...` のようなパス）
- アルバム名・フォルダ名
- iPhone の名前

## 対象範囲

| 対象 | 例 |
|---|---|
| ✅ 対象 | 保存先・キャッシュの外への書き込み／移動、`_album_state.json` の改変による誤動作、細工された写真データベースによる誤動作 |
| ❌ 対象外 | iPhone・iOS・Apple のサービス自体の問題 |
| ❌ 対象外（上流へ） | pymobiledevice3 などの依存ライブラリ自体の問題は、それぞれのプロジェクトへ報告してください |

## サポート対象のバージョン

修正は**最新版のみ**に行います。古い版をお使いの場合は、まず最新版で再現するかを確認してください。

## 返信の目安

個人開発のため、返信や修正に時間がかかることがあります。

- **受け取ったことの連絡**: 14日以内を目標にしています（約束はできません）
- **修正**: 時期はお約束できません。再現できた場合は、見通しをお知らせします
- **報奨金**: ありません

14日を過ぎても連絡がない場合は、同じ報告画面にコメントを追加してください。

## 報告内容の扱い

作者は、受け取った報告の整理（対象範囲に入るかの判断、再現条件の整理、返信文の下書き）に
AIツール（Anthropic Claude など）を使うことがあります。

- AIツールに渡すときは、ユーザー名などの個人を特定できる情報を伏せます
- 対象かどうかの判断と、返信の送信は作者が行います。AIが自動で返信することはありません

AIツールに渡してほしくない場合は、報告の中にその旨を書いてください。

---

## English (short)

Please do **not** open a public issue for security problems.
Use GitHub private vulnerability reporting:
https://github.com/xyzeton33/xyzeton-album-backup/security → "Report a vulnerability".
For ordinary bugs (errors, connection problems), use the "Bug report" issue form instead.

Include: app version, Windows version, the conditions needed (e.g. a junction inside the destination),
short numbered steps, and what was written/moved outside the destination.
Before pasting logs, mask your Windows user name, album names and device name.

I aim to acknowledge reports within 14 days, but cannot guarantee it. There is no fixed timeline for fixes.
Only the latest release receives fixes. This is a personal project; there is no bug bounty.

The maintainer may use AI tools (such as Anthropic Claude) to help organize reports
(scope check, reproduction notes, reply drafts). Personal identifiers are removed first,
and all decisions and replies are made by the maintainer — no automated replies.
If you do not want your report shared with AI tools, say so in the report.
