# -*- coding: utf-8 -*-
"""选题与正文生成：大纲先行、标题随后、分节续写、逐节摘要保持连贯。
四条风格线：悬疑（上头法则）/ 温情（情绪法则+纯真笔触白描，原纯文线已并入）/
严谨（强逻辑：本格悬疑、主神空间无限流，展示名"细腻写实"）/
二创（二创铁律+上头法则），选题数据自带 line 字段。"""
import json
import random
import re

import qc as qcmod
import db
import llm
import pools
import prompts


def _as_list(x):
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        for v in x.values():
            if isinstance(v, list):
                return v
    raise ValueError("模型没有返回JSON数组")


def _combo_text(c):
    if "base" in c:
        mode = pools.FAN_MODES.get(c.get("mode"), c.get("mode"))
        return (f"{c['main']}·{c['base']}·{c['ip']} × 身份「{c['role']}」"
                f" × 反差「{c['twist']}」 × 情怀「{c['emo']}」"
                f" × 模式「{mode}」")
    if "stake" in c:
        return (f"{c['main']}·{c['plot']}·{c['bg']}·{c['emo']}"
                f" × 谜面「{c['riddle']}」 × 破局「{c['gimmick']}」"
                f" × 利害「{c['stake']}」")
    if "engine" in c:
        return (f"{c['main']}·{c['plot']}·{c['bg']}·{c['emo']}"
                f" × 人设「{c['stance']}」 × 底牌「{c['engine']}」")
    return (f"{c['main']}·{c['plot']}·{c['emo']} × 内核「{c['core']}」"
            f" × 设定「{c['set']}」 × 意象「{c['obj']}」")


def _ln(line):
    return pools.LINE_NAMES.get(line, line)


def _gen_line_topics(n, log, line, hot=""):
    recent = [f"{t.get('title', '')}（{t.get('combo', '')}）"
              for t in db.recent_topics(30)]
    bench = db.bench_examples(line, 8)
    titles = [f"{b['title']}（{b['formula']}）" if b.get("formula") else b["title"]
              for b in bench]
    rng = random.SystemRandom()
    combos, seen = [], set()
    sampler = (pools.sample_combo if line == "悬疑"
               else pools.sample_fan_combo if line == "二创"
               else pools.sample_rigor_combo if line == "严谨"
               else pools.sample_warm_combo)
    while len(combos) < n:
        c = sampler(rng)
        sig = "|".join(str(v) for v in c.values())
        if sig in seen:
            continue
        seen.add(sig)
        combos.append(c)
    log(f"调用模型生成{_ln(line)}选题（{n} 个）…")
    hot_words = [hot] if hot else [
        w['word'] for w in db.latest_market_words(14)]
    if hot_words:
        log('注入书荒热词：' + '、'.join(hot_words[:8]))
    picks = hot_stories = None
    if not hot:  # 单词定向出题时保持聚焦，不掺整包
        picks = db.latest_market_picks(5) or None
        if picks:
            log('注入主编力签：' + '、'.join(p['title'] for p in picks))
        _rows, _seen = [], set()
        for s in sorted(db.latest_market_stories(120),
                        key=lambda x: 0 if x.get("subtab") == "黑马飙升" else 1):
            if s["title"] not in _seen:
                _seen.add(s["title"])
                _rows.append(s)
        hot_stories = _rows[:8] or None
        if hot_stories:
            log('注入热门故事榜：' + '、'.join(s['title'] for s in hot_stories[:4]) + '…')
    data = llm.ask_json(prompts.topic_messages(combos, recent, line,
                                          bench_titles=titles or None,
                                          hot_words=hot_words or None,
                                          picks=picks, hot_stories=hot_stories),
                   temperature=1.0, max_tokens=3000, log=log, want_list=True, item_key="title")
    items = _as_list(data)[:n]
    out = []
    for c, t in zip(combos, items):
        t = t if isinstance(t, dict) else {}
        t["combo"] = _combo_text(c)
        t["line"] = line
        if c.get("mode"):
            t["mode"] = c["mode"]
        flv = pools.maybe_flavor(rng, line)
        if flv:
            t["flavor"] = flv
            t["combo"] += f" + 调味「{flv}」"
        out.append(t)
    db.save_topics(out, source="combo")
    log(f"已生成 {len(out)} 个{_ln(line)}选题")
    return out


def gen_topics(n=6, log=print, line="悬疑", hot=""):
    """line：悬疑（无脑爽文）/ 温情（人间烟火）/ 严谨（细腻写实·强逻辑）/ 二创（二创改编）。
    hot：书荒热词（市场抓取），有则围绕它定向出选题。"""
    return _gen_line_topics(n, log, line, hot=hot)


# 字数档位：每节目标字数（全文固定 5 节，实际成稿通常为目标 7~9 成）
WORD_TIERS = {"标准": 1500, "加长": 2100, "特长": 2800}


def start_story(topic, log=print, sec_words=0):
    line = topic.get("line") or "悬疑"
    sec_words = int(sec_words or 0)
    if sec_words:
        log(f"字数档位：每节目标 {sec_words} 字，全文目标约 {sec_words * 5} 字")
    vr = pools.sample_variant(random.SystemRandom(), line)
    if vr:
        log(f"本篇风格变体：{vr['key']}（{vr['name']}）")
    openings = [b["opening"] for b in db.bench_examples(line, 3)
                if b.get("opening")]
    log("设计大纲与人物…")
    data = llm.ask_json(prompts.outline_messages(topic,
                                            bench_openings=openings or None),
                   temperature=0.8, max_tokens=3000, log=log, need_keys=["sections"])
    outline = data
    new_title = (topic.get("title") or "").strip()
    log("起吸睛标题…")
    try:
        tt = llm.ask_json(prompts.title_messages(topic, outline, line),
                          temperature=0.9, max_tokens=800, log=log,
                          need_keys=["titles"])
        cands = [c for c in (tt.get("titles") or [])
                 if isinstance(c, dict) and (c.get("text") or "").strip()]
        if cands:
            new_title = cands[0]["text"].strip()
            outline["title_options"] = cands
            log("定名《" + new_title + "》")
        else:
            log("标题候选为空，沿用选题标题")
    except Exception as exc:
        log("标题生成失败，沿用选题标题：" + str(exc))
    sid = db.create_story(topic, outline, title=new_title, sec_words=sec_words)
    db.update_story(sid, variant=(f"{vr['key']}·{vr['name']}" if vr else ""))
    total = len(outline.get("sections", [])) or 5
    for i in range(1, total + 1):
        log(f"撰写第 {i}/{total} 节…")
        story = db.get_story(sid)
        hooks = None
        if i == 1:  # 开篇参考：热门故事榜的真实开篇钩子
            _hs, _seen = [], set()
            for s in sorted(db.latest_market_stories(120),
                            key=lambda x: 0 if x.get("subtab") == "黑马飙升" else 1):
                b = (s.get("brief") or "").strip()
                if b and s["title"] not in _seen:
                    _seen.add(s["title"])
                    _hs.append(b)
            hooks = _hs[:4] or None
            if hooks:
                log("注入热门开篇钩子参考 ×" + str(len(hooks)))
        raw = llm.chat(prompts.section_messages(story, i, total, hooks=hooks),
                       temperature=llm.cfg("temperature_write", 0.85),
                       max_tokens=max(3500, int((story.get("sec_words") or 1350) * 2.2)))
        m = re.search(r"摘要[:：]\s*([^\n]+)", raw)
        summary = m.group(1).strip() if m else ""
        text = (raw[:m.start()] if m else raw).strip()
        text = re.sub(r"^```[a-z]*\n?|```$", "", text).strip()
        db.append_section(sid, i, text, summary)
    db.update_story(sid, status="generated")
    s = db.get_story(sid)
    log(f"完成《{s['title']}》，约 {s['word_count']} 字")
    return sid


def review_story(sid, log=print):
    story = db.get_story(sid)
    line = story.get("line") or "悬疑"
    log(f"AI审稿中（{_ln(line)}线标准：查时间线/人物/"
        f"{'煽情' if line == '温情' else '逻辑与伏笔' if line == '严谨' else '底牌与节奏'}）…")
    price = str((story.get("outline") or {}).get("price_paid") or "").strip()
    note = f"胜利成本（大纲 price_paid）：{price}" if price else None
    data = llm.ask_json(prompts.review_messages(story["title"], story["body"], line,
                                           outline_note=note),
                   temperature=0.3, max_tokens=2000, log=log, need_keys=["logic_score", "hook_score", "ai_risk", "issues"])
    db.update_story(sid, review_json=json.dumps(data, ensure_ascii=False))
    log("审稿完成")
    return data


def polish_story(sid, log=print):
    story = db.get_story(sid)
    chunks = _split_body(story["body"])
    out = []
    for mk, txt in chunks:
        if not txt.strip():
            continue
        label = f"「{mk}」" if mk else "全文"
        log(f"润色{label}…")
        new = llm.chat(prompts.polish_messages(txt, story["title"]),
                       temperature=0.5,
                       max_tokens=min(8000, max(4000, int(len(txt) * 1.5)))).strip()
        new = re.sub(r"^```[a-z]*\n?|```$", "", new).strip()
        out.append(f"{mk}\n{new}" if mk else new)
    body2 = db.clean_text("\n".join(out))
    db.update_story(sid, body=body2)
    log("润色完成")
    return body2

def _split_body(body):
    parts = re.split(r"\n+\s*([一二三四五六七八])\s*\n", "\n" + body)
    chunks = []
    if len(parts) >= 3:
        it = iter(parts[1:])
        for mk, txt in zip(it, it):
            chunks.append((mk, txt.strip()))
    else:
        paras = [p for p in body.split("\n") if p.strip()]
        mid = len(paras) // 2
        chunks = [("", "\n".join(paras[:mid])),
                  ("", "\n".join(paras[mid:]))]
    return chunks


def _load_json_field(story, key):
    raw = story.get(key) or ""
    try:
        return json.loads(raw) if raw else None
    except Exception:
        return None


def revise_story(sid, note, review_issues, qc_issues, ledger=None,
                 log=print):
    story = db.get_story(sid)
    line = story.get("line") or "悬疑"
    out = []
    for mk, txt in _split_body(story["body"]):
        if not txt.strip():
            continue
        label = f"「{mk}」" if mk else "全文"
        log(f"改稿{label}…")
        new = llm.chat(prompts.revise_messages(story["title"], line, note,
                                               review_issues, qc_issues,
                                               label, txt, ledger),
                       temperature=0.4,
                       max_tokens=min(8000, max(4000, int(len(txt) * 1.5)))).strip()
        new = re.sub(r"^```[a-z]*\n?|```$", "", new).strip()
        out.append(f"{mk}\n{new}" if mk else new)
    body2 = db.clean_text("\n".join(out))
    db.update_story(sid, body=body2)
    return body2


def ledger_story(story, log=print):
    data = llm.ask_json(prompts.ledger_messages(story["title"], story["body"]),
                        temperature=0.1, max_tokens=1500, log=log,
                        need_keys=["facts"])
    rows = []
    for f in (data.get("facts") or []):
        if isinstance(f, dict) and f.get("fact"):
            w = f.get("where", "")
            rows.append(f"- {f['fact']}={f.get('value', '')}" + (f"（{w}）" if w else ""))
    return chr(10).join(rows)


def _fmt_facts(facts):
    rows = []
    for f in facts or []:
        if not isinstance(f, dict) or not f.get("item"):
            continue
        row = f"- {f['item']}={f.get('value', '')}"
        bits = []
        if f.get("first_seen"):
            bits.append(f"首见{f['first_seen']}")
        if f.get("source_span"):
            bits.append(f"原文：{f['source_span']}")
        kb = f.get("known_by") or []
        if kb:
            bits.append("知道：" + "、".join(str(x) for x in kb))
        ua = f.get("used_at") or []
        if ua:
            bits.append("用于：" + "、".join(str(x) for x in ua))
        if bits:
            row += "（" + "；".join(bits) + "）"
        rows.append(row)
    return "\n".join(rows)


def fact_qc_story(story, log=print):
    """事实核对三连：抽取结构化事实 → 确定性交叉检查 → 逻辑审读（因果/数量级/
    常识/视角）。铁律：只报 issue，不改稿；修改一律交给 revise。"""
    out = {"issues": [], "uncertain": [], "skipped": False}
    try:
        log("抽取事实清单…")
        data = llm.ask_json(prompts.fact_messages(story["title"], story["body"]),
                            temperature=0.1, max_tokens=2500, log=log,
                            need_keys=["facts"])
        facts = [f for f in (data.get("facts") or [])
                 if isinstance(f, dict) and f.get("item")]
    except Exception as exc:
        log("事实抽取失败，跳过事实核对：" + str(exc))
        out["skipped"] = True
        return out
    for d in qcmod.cross_check_facts(facts):
        out["issues"].append({"type": "事实", "detail": d, "where": ""})
    facts_block = _fmt_facts(facts)
    try:
        log("逻辑审读（因果/数量级/常识/视角）…")
        lg = llm.ask_json(
            prompts.logic_review_messages(story["title"], story["body"], facts_block),
            temperature=0.2, max_tokens=1500, log=log, need_keys=["issues"])
        out["issues"] += [i for i in (lg.get("issues") or [])
                          if isinstance(i, dict)]
        out["uncertain"] = [u for u in (lg.get("uncertain") or [])
                            if isinstance(u, str)]
    except Exception as exc:
        log("逻辑审读失败，跳过：" + str(exc))
    return out


def audit_story(sid, note, ledger=None, log=print):
    story = db.get_story(sid)
    line = story.get("line") or "悬疑"
    o = _load_json_field(story, "outline_json") or {}
    chars = "、".join(str(c.get("name", "")) for c in (o.get("characters") or [])
                      if isinstance(c, dict) and c.get("name"))
    rows = []
    for c in (o.get("clues") or []):
        if isinstance(c, dict) and c.get("what"):
            rows.append(f"- {c['what']}（{c.get('planted', '?')}埋下，"
                        f"{c.get('payoff', '?')}揭晓）")
    clues = chr(10).join(rows)
    data = llm.ask_json(prompts.audit_messages(story["title"], line, note,
                                               chars, clues, story["body"], ledger),
                        temperature=0.2, max_tokens=1500, log=log,
                        need_keys=["note_done", "problems"])
    return data


def quality_loop(sid, note, log=print):
    story = db.get_story(sid)
    if story.get("status") == "published":
        log("该稿已发布，不再进入质量环")
        return None
    note = (note or "").strip()
    db.update_story(sid, note=note)
    log("质量环启动" + (f"：作者意见「{note[:30]}…」" if len(note) > 30
                       else (f"：作者意见「{note}」" if note else "（无意见，按清单修）")))

    qc = qcmod.local_qc(story)
    qc_issues = [f"[{lv}] {txt}" for lv, txt in qc["issues"]]
    rev = _load_json_field(story, "review_json")
    if not isinstance(rev, dict):
        log("尚无AI审稿报告，先审一轮作为改稿依据…")
        rev = review_story(sid, log)
    review_issues = rev.get("issues", []) if isinstance(rev, dict) else []

    fact_qc = fact_qc_story(story, log)
    review_issues = list(review_issues) + fact_qc["issues"]

    log("提取全书事实账本…")
    ledger = ledger_story(story, log)

    audits, passed = [], False
    rounds = 0
    for rounds in (1, 2):
        log(f"—— 质量环第 {rounds} 轮 ——")
        revise_story(sid, note, review_issues, qc_issues, ledger, log=log)
        audit = audit_story(sid, note, ledger, log=log)
        problems = [p for p in (audit.get("problems") or []) if isinstance(p, dict)]
        hard = [p for p in problems if (p.get("severity") or "block") == "block"]
        audits.append({"round": rounds,
                       "note_done": bool(audit.get("note_done")),
                       "problems": problems, "hard": len(hard)})
        if audit.get("note_done") and not hard:
            passed = True
            break
        review_issues = list(review_issues) + [
            {"type": "上轮校对未过", "detail": p.get("detail", ""),
             "where": p.get("where", "")} for p in hard]
        story = db.get_story(sid)
        qc = qcmod.local_qc(story)
        qc_issues = [f"[{lv}] {txt}" for lv, txt in qc["issues"]]

    log("终审评分…")
    final = review_story(sid, log)
    qc2 = qcmod.local_qc(db.get_story(sid))
    reasons = []
    if not passed and audits:
        last = [p for p in audits[-1]["problems"]
                if (p.get("severity") or "block") == "block"]
        reasons += [f"{p.get('where', '')}：{p.get('detail', '')}" for p in last]
        if not last:
            reasons.append("两轮校对仍未通过")
    hook = final.get("hook_score", 0) if isinstance(final, dict) else 0
    if hook < 60:
        reasons.append(f"终审抓人分 {hook}（<60，开头会被划走）")
    if any(lv == "block" for lv, _ in qc2["issues"]):
        reasons.append("质检存在RISK级敏感项，需人工确认")
    verdict = "通过" if passed and not reasons else "未过"
    report = {"note": note, "rounds": rounds, "audits": audits,
              "ledger": ledger,
              "fact_qc": {"issues": fact_qc["issues"],
                          "uncertain": fact_qc["uncertain"],
                          "skipped": fact_qc["skipped"]},
              "final": final, "qc_score": qc2["score"],
              "verdict": verdict, "reasons": reasons}
    db.update_story(sid, quality_json=json.dumps(report, ensure_ascii=False))
    if verdict == "通过":
        db.update_story(sid, status="approved")
        log("✓ 质量环通过，已自动批准入库")
    else:
        db.update_story(sid, status="rejected")
        log("✗ 质量环未过，已标记废弃（理由见质量环档案）")
    return report
