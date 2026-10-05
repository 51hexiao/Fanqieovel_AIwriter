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
CREATE TABLE IF NOT EXISTS market_words(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  board TEXT, kind TEXT, word TEXT, rank INTEGER, trend TEXT,
  captured_at TEXT
);
CREATE TABLE IF NOT EXISTS market_stories(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT, cats TEXT DEFAULT '', subtab TEXT DEFAULT '',
  author TEXT DEFAULT '', brief TEXT DEFAULT '', words TEXT DEFAULT '',
  insights TEXT DEFAULT '', captured_at TEXT
);
CREATE TABLE IF NOT EXISTS market_picks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT, pitch TEXT DEFAULT '', desc TEXT DEFAULT '',
  board TEXT DEFAULT '', kind TEXT DEFAULT '',
  captured_at TEXT
);
CREATE TABLE IF NOT EXISTS market_rules(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule TEXT, captured_at TEXT
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
        if "polish_json" not in cols:  # 润色完成标记（流水线「润色」步骤的完成依据）
            c.execute("ALTER TABLE stories ADD COLUMN polish_json TEXT DEFAULT ''")
        if "variant" not in cols:
            c.execute("ALTER TABLE stories ADD COLUMN variant TEXT DEFAULT ''")
        if "sec_words" not in cols:
            c.execute("ALTER TABLE stories ADD COLUMN sec_words INTEGER DEFAULT 0")
        tcols = {r[1] for r in c.execute("PRAGMA table_info(topics)")}
        if "used_count" not in tcols:
            c.execute("ALTER TABLE topics ADD COLUMN used_count INTEGER DEFAULT 0")
        mcols = {r[1] for r in c.execute("PRAGMA table_info(market_stories)")}
        if "cats" not in mcols:  # 旧库迁移：热门故事补题材标签列
            c.execute("ALTER TABLE market_stories ADD COLUMN cats TEXT DEFAULT ''")
        if "subtab" not in mcols:
            c.execute("ALTER TABLE market_stories ADD COLUMN subtab TEXT DEFAULT ''")
        for col in ("author", "brief", "words", "insights"):
            if col not in mcols:
                c.execute(f"ALTER TABLE market_stories ADD COLUMN {col} TEXT DEFAULT ''")
        pcols = {r[1] for r in c.execute("PRAGMA table_info(market_picks)")}
        for col in ("board", "kind"):  # 旧库迁移：主编力签补频道/类型列
            if col not in pcols:
                c.execute(f"ALTER TABLE market_picks ADD COLUMN {col} TEXT DEFAULT ''")
            c.execute("UPDATE topics SET used_count = 1 WHERE status = 'used'")
        # 2026-10-03 改版：原"纯文线"并入温情线，其键位由"严谨线"（强逻辑）取代。
        # 旧数据里的 纯文 一律归入 温情（那边存的本来就是温情向选题）。
        c.execute("UPDATE stories SET line='温情' WHERE line='纯文'")
        c.execute("UPDATE bench SET line='温情' WHERE line='纯文'")
        c.execute("UPDATE OR IGNORE bench_reports SET line='温情' WHERE line='纯文'")
        c.execute("DELETE FROM bench_reports WHERE line='纯文'")
        for r in c.execute("SELECT id, data_json FROM topics").fetchall():
            try:
                d = json.loads(r["data_json"] or "{}")
            except Exception:
                continue
            if isinstance(d, dict) and d.get("line") == "纯文":
                d["line"] = "温情"
                c.execute("UPDATE topics SET data_json=? WHERE id=?",
                          (json.dumps(d, ensure_ascii=False), r["id"]))


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
def create_story(topic, outline, title=None, sec_words=0):
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO stories(title,topic_json,outline_json,sections_json,"
            "summaries_json,body,word_count,status,line,sec_words,created_at,updated_at)"
            " VALUES(?,?,?,?,?,'',0,'generating',?,?,?,?)",
            (title or topic.get("title", ""),
             json.dumps(topic, ensure_ascii=False),
             json.dumps(outline, ensure_ascii=False), "[]", "[]",
             topic.get("line") or "悬疑", int(sec_words or 0), now(), now()))
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


def rebuild_body(sid):
    """从 sections_json 重建正文——编辑器旧快照覆盖丢稿后的自救。"""
    with _lock, _conn() as c:
        row = c.execute("SELECT sections_json FROM stories WHERE id=?",
                        (sid,)).fetchone()
        if not row:
            return 0
        secs = json.loads(row["sections_json"] or "[]")
        if not secs:
            return 0
        body = _assemble(secs)
        c.execute("UPDATE stories SET body=?, word_count=?, updated_at=? WHERE id=?",
                  (body, cjk_len(body), now(), sid))
        return len(body)


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


def save_market_words(rows):
    """整批替换当前快照（市场数据只留最新一期）。"""
    ts = now()
    with _lock, _conn() as c:
        c.execute("DELETE FROM market_words")
        c.executemany(
            "INSERT INTO market_words(board,kind,word,rank,trend,captured_at)"
            " VALUES(?,?,?,?,?,?)",
            [(r.get("board", ""), r.get("kind", ""), r.get("word", ""),
              int(r.get("rank") or 0), r.get("trend", ""), ts)
             for r in rows])
        return len(rows)


def save_market_stories(items):
    """整批替换热门故事快照；items 为 {title, cats, subtab, author, brief,
    words} 或纯标题字符串。"""
    ts = now()
    with _lock, _conn() as c:
        c.execute("DELETE FROM market_stories")
        c.executemany(
            "INSERT INTO market_stories"
            "(title,cats,subtab,author,brief,words,captured_at)"
            " VALUES(?,?,?,?,?,?,?)",
            [(it.get("title", "") if isinstance(it, dict) else str(it),
              (it.get("cats", "") if isinstance(it, dict) else ""),
              (it.get("subtab", "") if isinstance(it, dict) else ""),
              (it.get("author", "") if isinstance(it, dict) else ""),
              (it.get("brief", "") if isinstance(it, dict) else ""),
              (it.get("words", "") if isinstance(it, dict) else ""), ts)
             for it in items])
        return len(items)


def save_market_picks(rows):
    """整批替换主编力签快照。"""
    ts = now()
    with _lock, _conn() as c:
        c.execute("DELETE FROM market_picks")
        c.executemany(
            "INSERT INTO market_picks(title,pitch,desc,board,kind,captured_at)"
            " VALUES(?,?,?,?,?,?)",
            [(r.get("title", ""), r.get("pitch", ""), r.get("desc", ""),
              r.get("board", ""), r.get("kind", ""), ts)
             for r in rows])
        return len(rows)


def latest_market_picks(limit=10):
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT title,pitch,desc,board,kind,captured_at FROM market_picks"
            " ORDER BY id LIMIT ?", (limit,))]


def market_captured_at():
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT captured_at FROM market_words ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["captured_at"] if row else None


def latest_market_words(limit=80):
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT board,kind,word,rank,trend,captured_at FROM market_words"
            " ORDER BY board,kind,rank LIMIT ?", (limit,))]


def latest_market_stories(limit=120):
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT title,cats,subtab,author,brief,words,insights,captured_at"
            " FROM market_stories ORDER BY id LIMIT ?", (limit,))]


def save_story_insights(pairs):
    """按标题回写 AI 拆解结果：pairs = [(标题, insights_json), …]"""
    if not pairs:
        return 0
    with _lock, _conn() as c:
        c.executemany(
            "UPDATE market_stories SET insights=? WHERE title=?",
            [(ins, title) for title, ins in pairs])
        return len(pairs)


def save_market_rules(rules):
    """整批替换本周爆款写法规则快照。"""
    ts = now()
    with _lock, _conn() as c:
        c.execute("DELETE FROM market_rules")
        c.executemany("INSERT INTO market_rules(rule,captured_at) VALUES(?,?)",
                      [(str(r), ts) for r in rules])
        return len(rules)


def latest_market_rules(limit=8):
    with _lock, _conn() as c:
        return [r[0] for r in c.execute(
            "SELECT rule FROM market_rules ORDER BY id LIMIT ?", (limit,))]


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


def set_topic_tier(tid, tier):
    """字数档存在选题 data_json 里（免迁移），list_topics 会自动带出。"""
    with _lock, _conn() as c:
        row = c.execute("SELECT data_json FROM topics WHERE id=?", (tid,)).fetchone()
        if not row:
            return False
        d = json.loads(row["data_json"])
        d["tier"] = tier
        c.execute("UPDATE topics SET data_json=? WHERE id=?",
                  (json.dumps(d, ensure_ascii=False), tid))
        return True


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


