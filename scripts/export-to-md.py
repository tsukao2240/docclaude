#!/usr/bin/env python3
"""
Claude Code Stop hook: JSONLの会話ログをObsidian向けMarkdownに変換して保存する
"""

import json
import re
import sys
import os
import signal
import subprocess
from datetime import datetime
from pathlib import Path

# ローカル出力先
LOCAL_BASE = Path.home() / "claude-sessions"
# Windows転送先（WSLパス）
WIN_BASE = Path("/mnt/d/メモ/log")
PENDING_DIR = Path("/tmp/export-to-md-pending")

# キーワードベースの自動タグ
TAG_KEYWORDS = {
    "python":     ["python", ".py", "pip", "pytest", "django", "flask", "fastapi"],
    "javascript": ["javascript", "node", "npm", "yarn", ".js", "express"],
    "typescript": ["typescript", ".ts", "tsx"],
    "react":      ["react", "jsx", "tsx", "next.js", "nextjs"],
    "rust":       ["rust", "cargo", ".rs"],
    "go":         ["golang", " go ", ".go"],
    "shell":      ["bash", "zsh", "shell", ".sh"],
    "docker":     ["docker", "dockerfile", "compose"],
    "git":        ["git ", "github", "gitlab", "commit", "branch", "merge"],
    "wsl":        ["wsl", "/mnt/", "windows"],
    "obsidian":   ["obsidian", "vault", "frontmatter", "dataview"],
    "sql":        ["sql", "database", "postgres", "mysql", "sqlite"],
    "api":        ["api", "rest", "graphql", "endpoint", "fetch", "curl"],
    "claude":     ["claude", "anthropic", "llm", "prompt"],
    "hook":       ["hook", "settings.json", "stop hook"],
    "markdown":   ["markdown", ".md", "frontmatter"],
}

# ファイルパスを取り出すツール名とそのinputキー
FILE_READ_TOOLS  = {"Read": "file_path", "Grep": "path"}
FILE_WRITE_TOOLS = {"Edit": "file_path", "Write": "file_path"}


# ── データ読み込み ────────────────────────────────────────────

def read_transcript(path: str) -> list:
    messages = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("type") in ("user", "assistant"):
                    messages.append(entry)
            except json.JSONDecodeError:
                continue
    return messages


def build_ordered_messages(messages: list) -> list:
    def get_children(uuid):
        return [m for m in messages if m.get("parentUuid") == uuid and not m.get("isSidechain")]

    roots = [m for m in messages if not m.get("parentUuid") and not m.get("isSidechain")]
    if not roots:
        return messages

    ordered, visited = [], set()
    current = roots[0]
    while current:
        uid = current.get("uuid")
        if not uid or uid in visited:
            break
        visited.add(uid)
        ordered.append(current)
        children = get_children(uid)
        current = children[0] if children else None
    return ordered


# ── テキスト抽出 ─────────────────────────────────────────────

def extract_text(content, include_tools: bool = False) -> str:
    """会話の表示テキストのみ抽出（ツール呼び出しは除外）"""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text", "").strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def extract_tool_calls(messages: list) -> tuple[list, list, int]:
    """
    全メッセージのtool_useブロックを走査して
    参照ファイル・変更ファイル・ツール呼び出し総数を返す
    """
    read_files, written_files = [], []
    tool_count = 0

    for msg in messages:
        if msg.get("type") != "assistant":
            continue
        content = msg.get("message", {}).get("content", "")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_count += 1
            name = block.get("name", "")
            inp  = block.get("input", {})

            if name in FILE_WRITE_TOOLS:
                path = inp.get(FILE_WRITE_TOOLS[name], "")
                if path and path not in written_files:
                    written_files.append(path)
            elif name in FILE_READ_TOOLS:
                path = inp.get(FILE_READ_TOOLS[name], "")
                if path and path not in read_files and path not in written_files:
                    read_files.append(path)

    # 変更ファイルは参照リストから除外
    read_files = [p for p in read_files if p not in written_files]
    return read_files, written_files, tool_count


# ── メタデータ計算 ────────────────────────────────────────────

def parse_ts(ts: str):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
    except Exception:
        return None


def format_hms(ts: str) -> str:
    dt = parse_ts(ts)
    return dt.strftime("%H:%M:%S") if dt else ""


def extract_title(messages: list) -> str:
    for msg in messages:
        if msg.get("type") != "user":
            continue
        text = extract_text(msg.get("message", {}).get("content", "")).strip()
        if not text:
            continue
        # [Request interrupted by user] はスキップ
        if text.startswith("[Request interrupted"):
            continue
        first_line = text.splitlines()[0].strip()
        return first_line[:57] + "..." if len(first_line) > 60 else first_line
    return "Claude Session"


def slugify(text: str) -> str:
    text = text.strip()
    text = re.sub(r'[\\/:*?"<>|]', "", text)
    text = re.sub(r"\s+", "-", text)
    return text.strip("-")[:50]


def detect_tags(messages: list) -> list:
    full_text = " ".join(
        extract_text(m.get("message", {}).get("content", ""))
        for m in messages
    ).lower()
    tags = ["claude-session"]
    for tag, keywords in TAG_KEYWORDS.items():
        if any(kw in full_text for kw in keywords):
            tags.append(tag)
    return tags


def calc_duration(messages: list) -> str:
    times = [parse_ts(m.get("timestamp", "")) for m in messages]
    times = [t for t in times if t]
    if len(times) < 2:
        return ""
    total = int((times[-1] - times[0]).total_seconds())
    if total < 60:
        return f"{total}秒"
    elif total < 3600:
        return f"{total // 60}分"
    else:
        return f"{total // 3600}時間{(total % 3600) // 60}分"


def extract_project(cwd: str) -> str:
    return Path(cwd).name if cwd else ""


# ── Obsidian向けMarkdown生成 ──────────────────────────────────

def callout_body(text: str) -> str:
    """テキストをCallout内に収まる形式に変換"""
    return "\n".join("> " + line if line else ">" for line in text.splitlines())


def format_markdown(messages: list, session_id: str, cwd: str, title: str) -> str:
    now = datetime.now()
    tags = detect_tags(messages)
    duration = calc_duration(messages)
    project = extract_project(cwd)
    read_files, written_files, tool_count = extract_tool_calls(messages)

    user_count = sum(1 for m in messages if m.get("type") == "user")
    asst_count = sum(1 for m in messages if m.get("type") == "assistant")

    # ── YAML frontmatter ──
    tags_yaml = "\n".join(f"  - {t}" for t in tags)
    fm = ["---"]
    fm.append(f'title: "{title}"')
    fm.append(f"date: {now.strftime('%Y-%m-%d')}")
    fm.append(f"time: {now.strftime('%H:%M')}")
    fm.append(f"session_id: {session_id[:8]}")
    if project:
        fm.append(f"project: {project}")
    if cwd:
        fm.append(f"cwd: \"{cwd}\"")
    if duration:
        fm.append(f"duration: {duration}")
    fm.append(f"user_messages: {user_count}")
    fm.append(f"tool_calls: {tool_count}")
    fm.append(f"files_modified: {len(written_files)}")
    fm.append(f"files_read: {len(read_files)}")
    fm.append(f"tags:\n{tags_yaml}")
    fm.append("---")

    lines = ["\n".join(fm), ""]

    # ── タイトル ──
    lines.append(f"# {title}")
    lines.append("")

    # ── プロジェクトリンク（グラフビュー接続） ──
    if project:
        lines.append(f"> [!abstract] Project: [[{project}]]")
        lines.append("")

    # ── 作業ファイル一覧 ──
    if written_files or read_files:
        lines.append("## 作業ファイル")
        lines.append("")
        if written_files:
            lines.append("**変更・作成**")
            for p in written_files:
                lines.append(f"- `{p}`")
            lines.append("")
        if read_files:
            lines.append("**参照**")
            for p in read_files:
                lines.append(f"- `{p}`")
            lines.append("")

    # ── 指示の流れ（ユーザー発言のみ・中断除外） ──
    user_msgs = [
        m for m in messages
        if m.get("type") == "user"
        and not extract_text(m.get("message", {}).get("content", "")).strip().startswith("[Request interrupted")
    ]
    if user_msgs:
        lines.append("## 指示の流れ")
        lines.append("")
        for i, msg in enumerate(user_msgs, 1):
            text = extract_text(msg.get("message", {}).get("content", "")).strip()
            if not text:
                continue
            ts = format_hms(msg.get("timestamp", ""))
            ts_str = f" `{ts}`" if ts else ""
            first_line = text.splitlines()[0]
            if "\n" in text:
                rest = "\n".join(f"  > {l}" for l in text.splitlines()[1:] if l.strip())
                lines.append(f"{i}. {first_line}{ts_str}")
                if rest:
                    lines.append(rest)
            else:
                lines.append(f"{i}. {text}{ts_str}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 会話ログ")
    lines.append("")

    # ── 会話本文 ──
    for msg in messages:
        role = msg.get("type")
        if role not in ("user", "assistant"):
            continue

        text = extract_text(msg.get("message", {}).get("content", "")).strip()
        if not text:
            continue

        ts = format_hms(msg.get("timestamp", ""))
        ts_suffix = f" · {ts}" if ts else ""

        if role == "user":
            # ユーザー発言：常時展開
            lines.append(f"> [!question]+ User{ts_suffix}")
            lines.append(callout_body(text))
        else:
            # アシスタント：折りたたみ（長文でも邪魔にならない）
            lines.append(f"> [!info]- Assistant{ts_suffix}")
            lines.append(callout_body(text))

        lines.append("")

    return "\n".join(lines)


# ── Daily note追記 ────────────────────────────────────────────

def append_daily_note(base_dir: Path, session_file: Path, title: str, project: str):
    """
    base_dir/daily/YYYY-MM-DD.md にこのセッションへのリンクを追記する
    Obsidianのデイリーノートとの統合用
    """
    daily_dir = base_dir / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    daily_file = daily_dir / f"{date_str}.md"

    # セッションファイル名（拡張子なし）でwikilink
    link_name = session_file.stem
    project_str = f" `{project}`" if project else ""
    entry = f"- [[{link_name}]]{project_str} — {title}\n"

    if not daily_file.exists():
        daily_file.write_text(
            f"# {date_str}\n\n## Claude Sessions\n\n{entry}",
            encoding="utf-8"
        )
    else:
        content = daily_file.read_text(encoding="utf-8")
        if "## Claude Sessions" not in content:
            content += f"\n## Claude Sessions\n\n{entry}"
        elif link_name not in content:
            content = content.rstrip() + f"\n{entry}"
        daily_file.write_text(content, encoding="utf-8")


# ── Windows転送（遅延） ───────────────────────────────────────

def schedule_windows_copy(local_base: Path, win_base: Path, session_id: str):
    """
    60秒間Stopが来なければセッションファイルとdailyノートをWindowsにコピー
    （月別フォルダ構成を維持する）
    """
    if not win_base.exists():
        print(f"[export-to-md] Windows base not found: {win_base}", file=sys.stderr)
        return

    PENDING_DIR.mkdir(exist_ok=True)
    pid_file = PENDING_DIR / f"{session_id[:8]}.pid"

    if pid_file.exists():
        try:
            os.kill(int(pid_file.read_text()), signal.SIGTERM)
        except (ProcessLookupError, ValueError):
            pass

    # ローカルの月別フォルダをWindowsに丸ごと同期
    month_str = datetime.now().strftime("%Y-%m")
    local_month = local_base / month_str
    win_month   = win_base / month_str
    local_daily = local_base / "daily"
    win_daily   = win_base / "daily"

    script = (
        f"sleep 60 && "
        f"mkdir -p '{win_month}' '{win_daily}' && "
        f"rsync -a '{local_month}/' '{win_month}/' && "
        f"rsync -a '{local_daily}/' '{win_daily}/' && "
        f"echo '[export-to-md] Synced → {win_base}' >&2 && "
        f"rm -f '{pid_file}'"
    )
    proc = subprocess.Popen(
        ["bash", "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    pid_file.write_text(str(proc.pid))
    print(f"[export-to-md] Windows sync scheduled (pid={proc.pid}, delay=60s)", file=sys.stderr)


# ── エントリポイント ──────────────────────────────────────────

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    transcript_path = data.get("transcript_path", "")
    session_id      = data.get("session_id", "unknown")

    if not transcript_path:
        sys.exit(0)

    transcript_path = os.path.expanduser(transcript_path)
    if not os.path.exists(transcript_path):
        sys.exit(0)

    messages = read_transcript(transcript_path)
    if not messages:
        sys.exit(0)

    cwd     = messages[0].get("cwd", "") if messages else ""
    ordered = build_ordered_messages(messages)
    title   = extract_title(ordered)
    project = extract_project(cwd)

    md_content = format_markdown(ordered, session_id, cwd, title)

    # 月別サブフォルダに保存
    month_str  = datetime.now().strftime("%Y-%m")
    output_dir = LOCAL_BASE / month_str
    output_dir.mkdir(parents=True, exist_ok=True)

    slug        = slugify(title)
    short_id    = session_id[:8]
    date_str    = datetime.now().strftime("%Y-%m-%d")
    output_file = output_dir / f"{date_str}_{short_id}_{slug}.md"

    output_file.write_text(md_content, encoding="utf-8")
    print(f"[export-to-md] Saved → {output_file}", file=sys.stderr)

    # Daily note追記（ローカル）
    append_daily_note(LOCAL_BASE, output_file, title, project)
    print(f"[export-to-md] Daily note updated", file=sys.stderr)

    # Windowsへ遅延同期
    schedule_windows_copy(LOCAL_BASE, WIN_BASE, session_id)


if __name__ == "__main__":
    main()
