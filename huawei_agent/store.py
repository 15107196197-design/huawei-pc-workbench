from __future__ import annotations

import copy
import json
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from .settings import DATA


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def connection():
    db = sqlite3.connect(DATA / "studio.sqlite3", timeout=15)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, owner TEXT, payload TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS versions (id TEXT PRIMARY KEY, task_id TEXT, label TEXT, created_at TEXT, payload TEXT)")
    return db


def create_task(title: str = "新的内容任务", owner: str = "local") -> dict:
    task = {"id": uuid.uuid4().hex, "owner": owner, "title": title[:100], "brief": {
        "audience": "", "scenario": "", "goal": "", "platform": "wechat", "product": "",
        "budget": "", "region": "杭州", "purchase_stage": "", "software": "",
        "channels": ["华为商城", "淘宝", "闲鱼", "小红书", "微信小程序", "京东华为自营", "线下门店"]},
        "messages": [], "facts": [], "assets": [], "draft": None,
        "checks": [], "quotes": {"quotes": [], "best": [], "warnings": []},
        "versions": [], "status": "needs_input", "stage": "需求理解", "mode": "rules",
        "revision": 0, "created_at": now(), "updated_at": now(), "evidence": [],
        "price_evidence": [], "offers": [], "error": "",
        "requirement_events": [], "candidates": [], "fit_assessments": [],
        "selling_point_plan": {}, "evidence_refs": [], "claim_support": []}
    return save_task(task, "创建任务", version=False)


def get_task(task_id: str, owner: str | None = None) -> dict:
    with connection() as db:
        row = db.execute("SELECT owner,payload FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row or (owner is not None and row[0] != owner):
            raise KeyError("任务不存在")
        task = json.loads(row[1])
        task["versions"] = [{"id": v[0], "label": v[1], "created_at": v[2]} for v in
                            db.execute("SELECT id,label,created_at FROM versions WHERE task_id=? ORDER BY rowid DESC", (task_id,)).fetchall()]
        return task


def list_tasks(owner: str = "local") -> list[dict]:
    with connection() as db:
        rows = db.execute("SELECT payload FROM tasks WHERE owner=? ORDER BY rowid DESC", (owner,)).fetchall()
    tasks = [json.loads(r[0]) for r in rows]
    return sorted([{k: t.get(k) for k in ["id", "title", "updated_at", "status", "revision"]} |
                   {"platform": t["brief"].get("platform")} for t in tasks], key=lambda x: x["updated_at"], reverse=True)


def save_task(task: dict, label: str = "保存", version: bool = True, expected_revision: int | None = None) -> dict:
    t = copy.deepcopy(task)
    with connection() as db:
        old = db.execute("SELECT payload FROM tasks WHERE id=?", (t["id"],)).fetchone()
        old_revision = json.loads(old[0]).get("revision", 0) if old else 0
        if expected_revision is not None and old_revision != expected_revision:
            raise ValueError("内容已被更新，请重新打开后再保存")
        t["revision"] = old_revision + 1
        t["updated_at"] = now()
        t["versions"] = []
        db.execute("INSERT INTO tasks(id,owner,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                   (t["id"], t.get("owner", "local"), json.dumps(t, ensure_ascii=False)))
        if version:
            db.execute("INSERT INTO versions VALUES(?,?,?,?,?)", (uuid.uuid4().hex, t["id"], label[:120], now(), json.dumps(t, ensure_ascii=False)))
    return get_task(t["id"])


def restore(task_id: str, version_id: str, owner: str = "local") -> dict:
    current = get_task(task_id, owner)
    with connection() as db:
        row = db.execute("SELECT payload FROM versions WHERE task_id=? AND id=?", (task_id, version_id)).fetchone()
    if not row:
        raise KeyError("版本不存在")
    previous = json.loads(row[0])
    previous["messages"] = current["messages"]
    previous["checks"] = [c for c in previous.get("checks", []) if c.get("status") == "blocked"] + [{"category": "版本", "status": "warning", "message": "已恢复历史版本；交付前请重新核验当前价格和资料。"}]
    previous["status"] = "blocked" if any(c.get("status") == "blocked" for c in previous["checks"]) else "draft"
    return save_task(previous, "恢复历史版本")
