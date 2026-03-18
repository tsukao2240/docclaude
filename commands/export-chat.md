# Export Chat

現在のセッションの会話をMarkdownファイルに書き出してください。

以下の手順で実行してください：

1. 現在のセッションIDとJSONLパスを特定する（`~/.claude/projects/` 配下の現在のセッションファイル）
2. `python3 /home/tsukao/.claude/scripts/export-to-md.py` を、以下のJSONをstdinに渡して実行する：
   ```
   {"session_id": "<現在のsession_id>", "transcript_path": "<jsonlファイルのパス>"}
   ```
3. 出力先ファイルパスをユーザーに伝える

もし直接実行できない場合は、Bashツールで以下を実行：
```bash
echo '{"session_id": "SESSION_ID", "transcript_path": "JSONL_PATH"}' | python3 /home/tsukao/.claude/scripts/export-to-md.py
```
