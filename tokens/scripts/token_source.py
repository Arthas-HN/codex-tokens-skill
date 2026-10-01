"""Read-only Codex token monitor. Standard library only; no model/API calls."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import sqlite3
import threading
import time
from datetime import datetime, timezone



FIELDS = {"input": "input_tokens", "cachedInput": "cached_input_tokens",
          "output": "output_tokens", "reasoningOutput": "reasoning_output_tokens",
          "total": "total_tokens"}


def usage_values(raw):
    if not isinstance(raw, dict) or "total_tokens" not in raw:
        return None
    return {key: max(0, int(raw.get(value) or 0)) for key, value in FIELDS.items()}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_path(value):
    value = str(value or ".")
    if value.startswith("\\\\?\\"):
        value = value[4:]
    return os.path.normcase(os.path.abspath(value))


def compact_title(value):
    value = str(value or "未命名任务").strip()
    # Some imported chats store their original prompt in the title column.
    # Show a short label, never expand that prompt in the task picker.
    if value.startswith("## Referenced ChatGPT conversation"):
        match = re.search(r'"title"\s*:\s*"([^"\n]{1,100})"', value)
        value = "继续：" + match.group(1) if match else "导入的聊天"
    elif "## My request:" in value:
        value = value.split("## My request:", 1)[1].strip()
    value = " ".join(value.split())
    return value[:70] + ("…" if len(value) > 70 else "")


def parent_id(source):
    try:
        value = json.loads(source or "{}")
        if not isinstance(value, dict):
            return None
        return value.get("subagent", {}).get("thread_spawn", {}).get("parent_thread_id")
    except (ValueError, TypeError, AttributeError):
        return None


class TokenLog:
    """Incrementally consume complete JSONL records; never retain message content."""
    def __init__(self, path):
        self.path = Path(path)
        self.offset = 0
        self.pending = b""
        self.identity = None
        self.total = None
        self.recent = None
        self.limit = None
        self.latest = None
        self.status = "unknown"
        self.error = None
        self.generation = 0
        self.turn_id = None
        self.turn_totals = None

    def reset(self):
        self.offset = 0
        self.pending = b""
        self.total = self.recent = self.limit = self.latest = None
        self.status = "unknown"
        self.turn_totals = None
        self.generation += 1

    def refresh(self):
        try:
            stat = self.path.stat()
            identity = (stat.st_dev, stat.st_ino)
            if ((self.identity is not None and self.identity != identity)
                    or stat.st_size < self.offset):
                self.reset()
            self.identity = identity
            if stat.st_size > self.offset:
                with self.path.open("rb") as stream:
                    stream.seek(self.offset)
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        self.offset += len(chunk)
                        records = (self.pending + chunk).split(b"\n")
                        self.pending = records.pop()
                        for line in records:
                            # Skip all prose/tool records before decoding JSON.
                            if b'"event_msg"' not in line or not line.strip():
                                continue
                            try:
                                self.accept(json.loads(line))
                            except (ValueError, TypeError, OverflowError):
                                continue
                        # Avoid retaining an unusually large prose record in memory.
                        if len(self.pending) > 32 * 1024 * 1024:
                            self.pending = b""
            self.error = None
        except OSError:
            self.error = "任务记录暂时无法读取"

    def accept(self, obj):
        if not isinstance(obj, dict) or obj.get("type") != "event_msg":
            return
        payload = obj.get("payload") or {}
        if not isinstance(payload, dict):
            return
        kind = payload.get("type")
        if kind in ("task_started", "turn_started"):
            self.status = "running"
            self.turn_id = payload.get("turn_id")
            self.turn_totals = dict(self.total) if self.total else {key: 0 for key in FIELDS}
        elif kind in ("task_complete", "task_completed", "turn_completed"):
            self.status = "idle"
        elif kind in ("turn_aborted", "task_aborted"):
            self.status = "interrupted"
        elif kind == "token_count":
            info = payload.get("info")
            if not isinstance(info, dict):
                return
            total = usage_values(info.get("total_token_usage"))
            if total is not None:
                if self.total and total["total"] < self.total["total"]:
                    self.generation += 1
                self.total = total
                self.recent = usage_values(info.get("last_token_usage"))
                self.limit = info.get("model_context_window")
                self.latest = obj.get("timestamp")


class TokenStore:
    def __init__(self, codex_home, preferred_cwd=None, default_thread=None):
        self.home = Path(codex_home)
        candidates = [p for p in self.home.glob("state_*.sqlite") if p.stem[6:].isdigit()]
        self.db = max(candidates, key=lambda p: int(p.stem[6:])) if candidates else self.home / "state_5.sqlite"
        self.preferred_cwd = preferred_cwd
        self.default_thread = default_thread
        self.logs = {}
        self.lock = threading.RLock()
        self.metadata_at = 0.0
        self.roots = []
        self.edges = {}
        self.rows = {}
        self.metadata_error = None
        self.activate_window = threading.Event()

    def metadata(self):
        if self.roots and time.monotonic() - self.metadata_at < 1.5:
            return
        conn = None
        try:
            conn = sqlite3.connect(self.db.resolve().as_uri() + "?mode=ro", uri=True,
                                   timeout=0.5)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            columns = {r[1] for r in conn.execute("PRAGMA table_info(threads)")}
            desired = ["id", "rollout_path", "updated_at", "source", "cwd", "title", "model", "archived"]
            selected = [name for name in desired if name in columns]
            if "id" not in selected or "rollout_path" not in selected:
                raise ValueError("unsupported schema")
            # Read metadata only. Query no conversation, prompt, credentials or tool output.
            query = "SELECT " + ", ".join(selected) + " FROM threads"
            rows = [dict(r) for r in conn.execute(query)]
            for row in rows:
                row["title"] = compact_title(row.get("title"))
            edges = {}
            for row in rows:
                parent = parent_id(row.get("source"))
                if parent:
                    edges.setdefault(parent, set()).add(row["id"])
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "thread_spawn_edges" in tables:
                for edge in conn.execute("SELECT parent_thread_id, child_thread_id FROM thread_spawn_edges"):
                    edges.setdefault(edge[0], set()).add(edge[1])
            children = {child for group in edges.values() for child in group}
            roots = [r for r in rows if r["id"] not in children and not r.get("archived")]
            roots.sort(key=lambda r: r.get("updated_at") or 0, reverse=True)
            self.roots = roots[:100]
            self.rows = {r["id"]: r for r in rows}
            self.edges = edges
            self.metadata_error = None
        except (sqlite3.Error, OSError, ValueError):
            self.metadata_error = "暂时无法读取 Codex 任务目录，请确认 Codex 已运行"
        finally:
            if conn is not None:
                conn.close()
            self.metadata_at = time.monotonic()

    def choose(self):
        if self.default_thread and self.default_thread in self.rows:
            return self.default_thread
        if self.preferred_cwd:
            target = normalize_path(self.preferred_cwd)
            for row in self.roots:
                if normalize_path(row.get("cwd")) == target:
                    return row["id"]
        return self.roots[0]["id"] if self.roots else None

    def descendants(self, thread_id):
        found, pending = set(), list(self.edges.get(thread_id, ()))
        while pending:
            child = pending.pop()
            if child == thread_id or child in found:
                continue
            found.add(child)
            pending.extend(self.edges.get(child, ()))
        return sorted(found)

    def log(self, row):
        path = row.get("rollout_path")
        if not path:
            return None
        # Codex can persist an escaped Windows extended path prefix.
        if os.name == "nt" and path.startswith("\\\\?\\"):
            path = path[4:]
        value = self.logs.get(row["id"])
        if value is None or os.path.normcase(str(value.path)) != os.path.normcase(path):
            generation = value.generation + 1 if value else 0
            value = TokenLog(path)
            value.generation = generation
            self.logs[row["id"]] = value
        value.refresh()
        return value

    def snapshot(self, thread_id=None, children=True):
        with self.lock:
            self.metadata()
            selected_id = thread_id or self.choose()
            sessions = [{"id": r["id"], "title": r.get("title") or "未命名任务",
                         "cwd": r.get("cwd") or "", "updatedAt": r.get("updated_at"),
                         "status": self.logs[r["id"]].status if r["id"] in self.logs else "unknown"}
                        for r in self.roots]
            result = {"generatedAt": utc_now(), "refreshSeconds": 2,
                      "selectedId": selected_id, "sessions": sessions,
                      "selected": None, "error": self.metadata_error,
                      "source": "本机任务记录"}
            root = self.rows.get(selected_id)
            if root is None:
                result["error"] = result["error"] or "尚未找到可监控的任务"
                return result
            root_log = self.log(root)
            child_ids = self.descendants(selected_id) if children else []
            ids = [selected_id] + child_ids
            totals, missing, updated, generations = {k: 0 for k in FIELDS}, 0, [], []
            details = []
            for tid in ids:
                row = self.rows.get(tid)
                value = root_log if tid == selected_id else self.log(row) if row else None
                if value and value.total is not None and not value.error:
                    for key in FIELDS:
                        totals[key] += value.total[key]
                    if value.latest:
                        updated.append(value.latest)
                    generations.append(f"{tid}:{value.generation}")
                    details.append({"id": tid, "total": value.total["total"]})
                else:
                    missing += 1
            has_usage = missing < len(ids)
            recent = root_log.recent if root_log else None
            usage_error = root_log.error if root_log else "任务记录暂时无法读取"
            selected = {"id": selected_id, "title": root.get("title") or "未命名任务",
                        "cwd": root.get("cwd") or "", "model": root.get("model") or "",
                        "updatedAt": root.get("updated_at"), "status": root_log.status if root_log else "unknown",
                        "usage": totals if has_usage else None, "hasUsage": has_usage,
                        "childrenCount": len(child_ids), "missingUsageCount": missing,
                        "recentUsage": recent, "context": {"used": recent["total"] if recent else None,
                        "limit": root_log.limit if root_log else None},
                        "latestEventAt": max(updated) if updated else None,
                        "generation": "|".join(generations), "threadUsage": details,
                        "readError": usage_error}
            result["selected"] = selected
            if usage_error:
                result["error"] = result["error"] or usage_error
            return result

