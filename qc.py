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
