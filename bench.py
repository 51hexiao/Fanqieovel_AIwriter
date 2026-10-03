# -*- coding: utf-8 -*-
"""爆款拆解库：粘贴热门短故事 → 结构拆解 → 多篇共性提炼。
拆解结论会被选题和大纲提示词自动引用（只学结构，禁止抄情节）。"""
import db
import llm
import pools
import prompts


def disassemble_new(title, body, line, log=print):
    bid = db.add_bench(title, body, line)
    return disassemble(bid, log)


def disassemble(bid, log=print):
    item = db.get_bench(bid)
    log(f"拆解《{item['title']}》…")
    data = llm.ask_json(
        prompts.bench_messages(item["title"], item["body"], item["line"]),
        temperature=0.3, max_tokens=2000, log=log)
    db.save_bench_analysis(bid, data)
    log("拆解完成")
    return data


def _digest(it):
    d = it.get("data") or {}
    cliffs = "、".join(d.get("cliff_types") or [])
    twists = "；".join(f"{t.get('where', '')}，{t.get('what', '')}"
                       for t in (d.get("twists") or []) if isinstance(t, dict))
    tags = "、".join(d.get("theme_tags") or [])
    return (f"《{it['title']}》 标题句式:{d.get('title_formula', '')}｜"
            f"开篇:{d.get('opening_type', '')}｜断章:{cliffs}｜反转:{twists}｜"
            f"题材:{tags}")


def build_report(line, log=print):
    items = [it for it in db.list_bench(line) if it.get("data")]
    if len(items) < 2:
        ln = pools.LINE_NAMES.get(line, line)
        raise RuntimeError(f"{ln}线目前只有 {len(items)} 篇拆解，先多拆几篇"
                           f"（至少 2 篇）再生成共性报告")
    log(f"汇总 {len(items)} 篇拆解，提炼共性…")
    data = llm.ask_json(
        prompts.bench_report_messages("\n".join(_digest(it) for it in items),
                                      len(items), line),
        temperature=0.3, max_tokens=2000, log=log)
    data["sample_count"] = len(items)
    db.save_bench_report(line, data)
    log("共性报告完成，选题和大纲会自动参考")
    return data
