"""Print a one-time token snapshot for the calling Codex chat."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

from token_source import TokenStore


def local_stamp(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, AttributeError):
        return "尚未记录"


def render(snapshot):
    selected = snapshot.get("selected")
    if not selected or not selected.get("hasUsage") or selected.get("readError"):
        return "Token 状态：" + (snapshot.get("error") or "等待可用的统计记录。")
    usage = selected["usage"]
    included = selected["childrenCount"]
    scope = f"当前聊天累计，含 {included} 个子任务" if included else "当前聊天累计，主任务"
    lines = [f"Token 状态 · {scope}", "", "| 项目 | Token |", "| --- | ---: |",
             f"| 总计 | {usage['total']:,} |", f"| 输入 | {usage['input']:,} |",
             f"| 输出 | {usage['output']:,} |", f"| 缓存输入（已计入输入） | {usage['cachedInput']:,} |",
             f"| 推理输出（已计入输出） | {usage['reasoningOutput']:,} |", "",
             f"记录时间：{local_stamp(selected.get('latestEventAt'))}（北京时间）。"]
    missing = selected.get("missingUsageCount", 0)
    if missing:
        lines.append(f"还有 {missing} 个任务尚未取得统计；上述为已记录的部分，后续可再次查询。")
    if snapshot.get("error"):
        lines.append(snapshot["error"])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="查询当前 Codex 聊天 Token 状态，无需打开监控小窗")
    parser.add_argument("--thread", default=os.environ.get("CODEX_THREAD_ID"))
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME") or str(Path.home()/".codex"))
    parser.add_argument("--main-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.thread:
        message = "无法识别当前聊天，请提供已确认的聊天 ID（--thread）。"
        print(json.dumps({"error": message}, ensure_ascii=False) if args.json else "Token 状态：" + message)
        return 2
    store = TokenStore(args.codex_home)
    result = store.snapshot(thread_id=args.thread, children=not args.main_only)
    if result.get("selectedId") != args.thread:
        print("Token 状态：当前聊天身份无法确认。")
        return 2
    if args.json:
        # Return only the requested chat's statistics, not the other task titles.
        result.pop("sessions", None)
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(render(result))
    return 0 if result.get("selected") and not result.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
