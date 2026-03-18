# dotclaude

Claude Code の個人設定・フック・カスタムコマンドを管理するリポジトリ。

## 構成

```
.claude/
├── settings.json          # Claude Code グローバル設定・フック定義
├── scripts/
│   └── export-to-md.py    # Stop hookで会話ログをMarkdownに変換するスクリプト
└── commands/
    └── export-chat.md     # カスタムコマンド
```

## 主な機能

### 会話ログの自動エクスポート（Stop hook）

Claude Code のセッションが終了するたびに、会話ログを Obsidian 向けの Markdown ファイルとして自動保存する。

**出力先**
- ローカル: `~/claude-sessions/YYYY-MM/`
- Windows: `D:\メモ\log\YYYY-MM\`（WSL環境の場合、セッション終了60秒後に同期）

**生成されるファイル**

```
~/claude-sessions/
├── 2026-03/
│   └── 2026-03-19_b86f3b72_タイトル.md   # セッションログ
└── daily/
    └── 2026-03-19.md                      # デイリーノート（当日のセッション一覧）
```

**Markdownの内容**

| セクション | 内容 |
|-----------|------|
| YAML frontmatter | date, project, tags, duration, files_modified, tool_calls など |
| 作業ファイル | セッション中に変更・参照したファイルの一覧 |
| 指示の流れ | ユーザーの発言のみ時系列で抽出（中断メッセージは除外） |
| 会話ログ | Callout形式（User: 常時展開 / Assistant: 折りたたみ） |

**Obsidian との統合**
- タグパネル・Dataview プラグインで検索・フィルタ可能
- `[[project名]]` wikilink でグラフビューに接続
- デイリーノートにセッションリンクを自動追記

## セットアップ

```bash
git clone https://github.com/<your-username>/dotclaude ~/.claude
```

**WSL環境の場合**、`export-to-md.py` の以下の定数を環境に合わせて変更する：

```python
WIN_BASE = Path("/mnt/d/メモ/log")   # Windows側の保存先
```

## 依存

- Python 3.8+
- rsync（Windows同期に使用）
- Claude Code
