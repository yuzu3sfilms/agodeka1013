# AI橋本新 v2.3.1 import fix

Render crash fix.

原因:
`bot_core.py` が `from anti_echo import finalize` していたが、
`anti_echo.py` 側には `finalize_reply` しかなかった。

修正:
- `bot_core.py` を `finalize_reply` に統一
- 念のため `anti_echo.py` に `finalize` aliasも追加

GitHubをこのZIPの中身で上書きしてDeploy。
