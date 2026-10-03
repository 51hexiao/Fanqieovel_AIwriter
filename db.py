# -*- coding: utf-8 -*-
"""SQLite 存储：稿件、选题、已用人名。"""
import json
import re
import sqlite3
import threading
from datetime import datetime

import paths

DB_PATH = paths.DATA_DIR / "data.db"
MARKERS = ["一", "二", "三", "四", "五", "六", "七", "八"]
_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def init():
    with _lock, _conn() as c:
        c.executescript("""
CREATE TABLE IF NOT EXISTS stories(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT DEFAULT '',
  topic_json TEXT DEFAULT '',
  outline_json TEXT DEFAULT '',
  sections_json TEXT DEFAULT '[]',
  summaries_json TEXT DEFAULT '[]',
  body TEXT DEFAULT '',
  word_count INTEGER DEFAULT 0,
  status TEXT DEFAULT 'generating',
  line TEXT DEFAULT '悬疑',
  qc_json TEXT DEFAULT '',
  review_json TEXT DEFAULT '',
  quality_json TEXT DEFAULT '',
  note TEXT DEFAULT '',
  created_at TEXT, updated_at TEXT, published_at TEXT
);
CREATE TABLE IF NOT EXISTS topics(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  data_json TEXT, status TEXT DEFAULT 'new',
  used_count INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS used_names(name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS bench(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT DEFAULT '', line TEXT DEFAULT '悬疑',
  body TEXT DEFAULT '', data_json TEXT DEFAULT '',
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS bench_reports(
  line TEXT PRIMARY KEY, data_json TEXT DEFAULT '', created_at TEXT
);
""")
        cols = {r[1] for r in c.execute("PRAGMA table_info(stories)")}
        if "line" not in cols:  # 旧库迁移
            c.execute("ALTER TABLE stories ADD COLUMN line TEXT DEFAULT '悬疑'")
        cols = {r[1] for r in c.execute("PRAGMA table_info(stories)")}
        cols = {r[1] for r in c.execute("PRAGMA table_info(stories)")}
        if "quality_json" not in cols:
            c.execute("ALTER TABLE stories ADD COLUMN quality_json TEXT DEFAULT ''")
        tcols = {r[1] for r in c.execute("PRAGMA table_info(topics)")}
        if "used_count" not in tcols:
            c.execute("ALTER TABLE topics ADD COLUMN used_count INTEGER DEFAULT 0")
            c.execute("UPDATE topics SET used_count = 1 WHERE status = 'used'")


def cjk_len(s):
    return len(re.findall(r"[\u4e00-\u9fff]", s or ""))


def clean_text(text):
    """正文统一单换行分段：编辑器显示与番茄粘贴都不会出现空行。"""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return re.sub(r"\n{2,}", "\n", t)


def _assemble(sections):
    secs = sorted(sections, key=lambda x: x["no"])
    return "\n".join(
        f"{MARKERS[s['no'] - 1]}\n{clean_text(s['text'])}" for s in secs)


# ---------- 稿件 ----------
def create_story(topic, outline, title=None):
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO stories(title,topic_json,outline_json,sections_json,"
            "summaries_json,body,word_count,status,line,created_at,updated_at)"
            " VALUES(?,?,?,?,?,'',0,'generating',?,?,?)",
            (title or topic.get("title", ""),
             json.dumps(topic, ensure_ascii=False),
             json.dumps(outline, ensure_ascii=False), "[]", "[]",
             topic.get("line") or "悬疑", now(), now()))
        return cur.lastrowid


def _parse(row):
    if row is None:
        return None
    d = dict(row)
    d["topic"] = json.loads(d.pop("topic_json") or "{}")
    d["outline"] = json.loads(d.pop("outline_json") or "{}")
    d["sections"] = json.loads(d.pop("sections_json") or "[]")
    d["summaries"] = json.loads(d.pop("summaries_json") or "[]")
    return d


def get_story(sid):
    with _lock, _conn() as c:
        return _parse(c.execute(
            "SELECT * FROM stories WHERE id=?", (sid,)).fetchone())


def list_stories():
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id,title,word_count,status,line,created_at,updated_at,"
            "published_at FROM stories ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def update_story(sid, **fields):
    if "body" in fields:
        fields["body"] = clean_text(fields["body"])
        fields["word_count"] = cjk_len(fields["body"])
    fields["updated_at"] = now()
    cols = ",".join(f"{k}=?" for k in fields)
    with _lock, _conn() as c:
        c.execute(f"UPDATE stories SET {cols} WHERE id=?",
                  (*fields.values(), sid))


def append_section(sid, no, text, summary):
    with _lock, _conn() as c:
        row = c.execute("SELECT sections_json FROM stories WHERE id=?",
                        (sid,)).fetchone()
        secs = json.loads(row["sections_json"] or "[]")
        secs = [s for s in secs if s["no"] != no]
        secs.append({"no": no, "text": text, "summary": summary})
        secs.sort(key=lambda x: x["no"])
        body = _assemble(secs)
        c.execute(
            "UPDATE stories SET sections_json=?, summaries_json=?, body=?,"
            " word_count=?, updated_at=? WHERE id=?",
            (json.dumps(secs, ensure_ascii=False),
             json.dumps([s["summary"] for s in secs], ensure_ascii=False),
             body, cjk_len(body), now(), sid))


def delete_story(sid):
    with _lock, _conn() as c:
        c.execute("DELETE FROM stories WHERE id=?", (sid,))


# ---------- 选题 ----------
def save_topics(items, source="combo"):
    with _lock, _conn() as c:
        for t in items:
            t = dict(t)
            t["source"] = source
            c.execute("INSERT INTO topics(data_json,created_at) VALUES(?,?)",
                      (json.dumps(t, ensure_ascii=False), now()))


def add_topic(title, hook="", social="", hot="", diff="", line="悬疑"):
    t = {"title": title, "hook": hook, "social": social, "hot": hot,
         "diff": diff, "combo": "", "source": "manual", "line": line}
    with _lock, _conn() as c:
        cur = c.execute("INSERT INTO topics(data_json,created_at) VALUES(?,?)",
                        (json.dumps(t, ensure_ascii=False), now()))
        return cur.lastrowid


def delete_topic(tid):
    with _lock, _conn() as c:
        c.execute("DELETE FROM topics WHERE id=?", (tid,))


def list_topics(status=None, line=None):
    q = "SELECT * FROM topics"
    args = ()
    if status:
        q, args = "SELECT * FROM topics WHERE status=?", (status,)
    with _lock, _conn() as c:
        rows = c.execute(q + " ORDER BY id DESC LIMIT 100", args).fetchall()
        out = []
        for r in rows:
            d = json.loads(r["data_json"])
            if line and d.get("line") != line:
                continue
            d["id"] = r["id"]
            d["status"] = r["status"]
            d["used_count"] = r["used_count"] if "used_count" in r.keys() else 0
            out.append(d)
        return out


def use_topic(tid):
    with _lock, _conn() as c:
        c.execute("UPDATE topics SET status='used', used_count=used_count+1 WHERE id=?", (tid,))


def recent_topics(n=30):
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT data_json FROM topics WHERE status='used'"
            " ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [json.loads(r["data_json"]) for r in rows]


# ---------- 爆款拆解库 ----------
def add_bench(title, body, line):
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO bench(title,line,body,created_at) VALUES(?,?,?,?)",
            (title, line, body, now()))
        return cur.lastrowid


def save_bench_analysis(bid, data):
    with _lock, _conn() as c:
        c.execute("UPDATE bench SET data_json=? WHERE id=?",
                  (json.dumps(data, ensure_ascii=False), bid))


def get_bench(bid):
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM bench WHERE id=?", (bid,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["data"] = json.loads(d.pop("data_json") or "{}")
    return d


def list_bench(line=None):
    q = "SELECT id,title,line,data_json,created_at FROM bench"
    args = ()
    if line:
        q, args = q + " WHERE line=?", (line,)
    q += " ORDER BY id DESC LIMIT 100"
    with _lock, _conn() as c:
        out = []
        for r in c.execute(q, args).fetchall():
            d = dict(r)
            d["data"] = json.loads(d.pop("data_json") or "{}")
            out.append(d)
        return out


def delete_bench(bid):
    with _lock, _conn() as c:
        c.execute("DELETE FROM bench WHERE id=?", (bid,))


def bench_examples(line, n=8):
    """已拆解爆款的精华，供选题/大纲提示词引用。"""
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT title,data_json FROM bench WHERE line=? AND data_json!=''"
            " ORDER BY id DESC LIMIT ?", (line, n)).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["data_json"] or "{}")
        out.append({"title": r["title"],
                    "formula": d.get("title_formula", ""),
                    "opening_type": d.get("opening_type", ""),
                    "opening": d.get("opening", "")})
    return out


def save_bench_report(line, data):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO bench_reports(line,data_json,created_at) VALUES(?,?,?)"
            " ON CONFLICT(line) DO UPDATE SET data_json=excluded.data_json,"
            " created_at=excluded.created_at",
            (line, json.dumps(data, ensure_ascii=False), now()))


def get_bench_report(line):
    with _lock, _conn() as c:
        row = c.execute("SELECT data_json FROM bench_reports WHERE line=?",
                        (line,)).fetchone()
        return json.loads(row["data_json"]) if row else None


