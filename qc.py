# -*- coding: utf-8 -*-
"""本地质检：不花钱、瞬时完成的规则检查。AI腔、重复句、段落节奏、
敏感词、标题长度。"""
import re

import db
import paths

# 词：允许出现次数（达到该次数才提醒）
CLICHE = {
    "总而言之": 1, "综上所述": 1, "值得注意的是": 1, "与此同时": 3,
    "在这个": 3, "不仅仅": 2, "或许": 4, "也许": 4, "仿佛": 4,
    "一丝": 3, "一抹": 2, "眼眸": 1, "嘴角勾起": 1, "空气仿佛": 1,
    "时间仿佛": 1, "心底涌起": 1, "深深地": 2, "深深地吸": 2,
}

SENSITIVE = [
    ("自杀教程", "block"), ("器官买卖", "block"), ("邪教", "block"),
    ("暴恐", "block"), ("代孕", "warn"), ("上吊", "warn"),
    ("安眠药", "warn"), ("坠楼", "warn"), ("开房记录", "warn"),
    ("偷拍", "warn"), ("性侵", "warn"), ("裸聊", "warn"),
    ("赌博", "warn"), ("毒品", "warn"),
]
_extra = paths.DATA_DIR / "sensitive.txt"
if _extra.exists():
    for _line in _extra.read_text(encoding="utf-8").splitlines():
        _w = _line.strip()
        if _w and not _w.startswith("#"):
            SENSITIVE.append((_w, "warn"))

def local_qc(story):
    title, body = story.get("title", ""), story.get("body", "")
    issues = []

    wc = db.cjk_len(body)
    if wc < 5500:
        issues.append(["warn", f"正文约 {wc} 字，短故事建议 6000 字以上"])
    elif wc > 12000:
        issues.append(["info", f"正文约 {wc} 字，偏长，注意节奏"])

    paras = [p for p in body.split("\n") if p.strip()]
    ones = [p for p in paras
            if db.cjk_len(p) <= 15 and "“" not in p and "”" not in p]
    ratio = len(ones) / max(len(paras), 1)
    if ratio > 0.35:
        issues.append(["warn", f"一句话段落占比 {ratio:.0%}，"
                               f"叙述段建议合并为 3-5 句"])

    freq = {}
    for s in re.split(r"[。！？!?\n]", body):
        s = re.sub(r"\s", "", s)
        if len(s) >= 10:
            freq[s] = freq.get(s, 0) + 1
    for s, c in freq.items():
        if c > 1:
            issues.append(["warn", f"重复出现 {c} 次的句子：{s[:28]}…"])

    for w, limit in CLICHE.items():
        c = body.count(w)
        if c >= limit:
            issues.append(["info", f"高频表达「{w}」出现 {c} 次，建议替换"])

    if body.count("“") != body.count("”"):
        issues.append(["warn", "引号数量不配对，检查对话标点"])
    if not re.search(r"^五\s*$", body, re.M):
        issues.append(["info", "未找到「五」分节标记，确认结构完整"])

    if len(title) > 30:
        issues.append(["warn", f"标题 {len(title)} 字，番茄标题上限 30 字"])
    elif not title:
        issues.append(["warn", "标题为空"])

    for w, level in SENSITIVE:
        if w in body:
            issues.append(["block" if level == "block" else "warn",
                           f"敏感词「{w}」，发布前人工确认"])

    warn = sum(1 for i in issues if i[0] == "warn")
    info = sum(1 for i in issues if i[0] == "info")
    block = sum(1 for i in issues if i[0] == "block")
    score = max(0, 100 - block * 30 - warn * 12 - info * 4)
    return {"score": score, "word_count": wc,
            "para_one_ratio": round(ratio, 2),
            "issues": issues}


# ---------- 事实清单确定性交叉检查（只报不改，不改稿不重写） ----------
_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}
_CN_BIG = {"万": 10000, "亿": 100000000}
_VAGUE_CHARS = set("几多约近余")


def parse_num(text):
    """把 '八万' / '3千' / '1,500' / '三万五千' / '三万人' / '90人' 解析成数值。
    带计量后缀（人/车/石/年…）时取前段数词；模糊量（十几/三十多/约）返回 None。"""
    t = str(text or "").strip().replace("两", "二").replace(",", "").replace("，", "")
    if t.startswith("百分之"):
        t = t[3:]
    if not t or (_VAGUE_CHARS & set(t)):
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([万亿])", t)
    if m:
        v = float(m.group(1)) * _CN_BIG[m.group(2)]
        return int(v) if v == int(v) else v
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        f = float(t)
        return int(f) if f == int(f) else f
    total = section = digit = 0
    last_unit = 0
    saw_zero = False
    seen = False
    for ch in t:
        if ch in _CN_DIGIT:
            digit = _CN_DIGIT[ch]
            saw_zero = saw_zero or digit == 0
            seen = True
        elif ch.isdigit():
            digit = digit * 10 + int(ch)
            seen = True
        elif ch in _CN_UNIT:
            section += (digit or 1) * _CN_UNIT[ch]
            digit = 0
            last_unit = _CN_UNIT[ch]
            seen = True
        elif ch in _CN_BIG:
            total += ((section + digit) or 1) * _CN_BIG[ch]
            section = digit = 0
            last_unit = 0
            saw_zero = False
            seen = True
        elif seen:
            break
        else:
            return None
    if section and digit and last_unit >= 10 and not saw_zero:
        section += digit * (last_unit // 10)
        digit = 0
    return (total + section + digit) if seen else None


def _sec_no(s):
    m = re.search(r"第\s*(\d+)\s*节", str(s or ""))
    if m:
        return int(m.group(1))
    s = str(s or "")
    if "开篇" in s or "序" in s:
        return 0
    return None


def cross_check_facts(facts):
    """对事实清单做确定性交叉检查：同名事实数值冲突、事实被使用先于出现。
    返回问题字符串列表；只报 issue，修改交给 revise。"""
    issues = []
    by_item = {}
    for f in facts or []:
        if isinstance(f, dict) and f.get("item"):
            by_item.setdefault(str(f["item"]).strip(), []).append(f)
    for item, fs in by_item.items():
        vals = [(str(f.get("value") or ""), parse_num(f.get("value")),
                 f.get("first_seen") or "?") for f in fs]
        nums = {n for _, n, _ in vals if n is not None}
        if len(nums) > 1:
            detail = "；".join(f"{v}（{w}）" for v, _, w in vals if v)
            issues.append(f"事实「{item}」数值冲突：{detail}")
    for f in facts or []:
        if not isinstance(f, dict) or not f.get("item"):
            continue
        first = _sec_no(f.get("first_seen"))
        if first is None:
            continue
        for u in (f.get("used_at") or []):
            use = _sec_no(u)
            if use is not None and use < first:
                issues.append(f"事实「{f['item']}」首次出现于第{first}节，"
                              f"但第{use}节已被人物使用（信息穿越）")
                break
    return issues
