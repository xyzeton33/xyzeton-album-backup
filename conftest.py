"""テスト実行環境の補正（このプロジェクト専用）。

Windowsでは、管理者権限も開発者モードも無い環境で os.symlink を呼ぶと
OSError(WinError 1314) になり、テストが「失敗」として扱われてしまう。
実際には「この環境では検証できない」だけなので、
テストがこのエラーで失敗した場合に限り、結果を skip に読み替える。

os.symlink そのものは差し替えない。
pytest は一時フォルダ（tmp_path）を作るときに内部で os.symlink を使い、
権限が無ければ黙って無視する作りになっている。ここを差し替えると
tmp_path を使うテストがすべて巻き込まれてスキップされてしまう
（実際に 115件中104件がスキップされた）。
"""
import pytest

_SKIP_REASON = (
    "このPCではシンボリックリンクを作成できません"
    "（管理者権限で実行するか、設定→プライバシーとセキュリティ→開発者向け→"
    "開発者モード をオンにすると実行できます）"
)


def _is_symlink_privilege_error(exc):
    return isinstance(exc, OSError) and getattr(exc, "winerror", None) == 1314


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed or call.excinfo is None:
        return
    if _is_symlink_privilege_error(call.excinfo.value):
        report.outcome = "skipped"
        report.longrepr = (str(item.path), item.location[1] or 0,
                           "Skipped: " + _SKIP_REASON)
