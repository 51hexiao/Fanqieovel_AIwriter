# -*- coding: utf-8 -*-
"""冒烟测试：不起模型，验证接口与质检逻辑。"""
import time

from fastapi.testclient import TestClient

import app as appmod
import db

db.init()
c = TestClient(appmod.app)

# 1) 撞名检测已整体移除
qc_src = open("qc.py", encoding="utf-8").read()
assert "撞名" not in qc_src and "extract_names" not in qc_src
print("1) 撞名检测已移除: True")

# 2) 未配置 Key 时，选题任务应给出友好报错而非崩溃
tid = c.post("/api/topics/generate").json()["task_id"]
for _ in range(20):
    t = c.get(f"/api/tasks/{tid}").json()
    if t["status"] != "running":
        break
    time.sleep(0.5)
print("2) 无Key选题任务:", t["status"], "|", (t.get("error") or "")[:40])

# 3) 造一篇测试稿，走 质检→改稿→批准→发布→导出 全流程
topic = {"title": "测试标题", "combo": "独居安全 × 保洁员 × 凶手主动报案 × 母女"}
outline = {"sections": [{"no": i, "beats": ["x"], "hook": "y"}
                        for i in range(1, 6)],
           "characters": [{"name": "林小满", "role": "主角", "secret": "无"}],
           "narrator": "我", "clues": []}
sid = db.create_story(topic, outline)
para = ("她把外卖放在门口，没有敲门。我数到三十才走过去。"
        "塑料袋上印着店名，备注写着不要按门铃。这样的早晨持续了七天。")
body = "\n\n".join(
    f"{m}\n\n{para * 6}" for m in ["一", "二", "三", "四", "五"])
db.update_story(sid, body=body)

qc = c.post(f"/api/stories/{sid}/qc").json()
assert "names" not in qc
print("3) 质检:", "得分", qc["score"], "| 字数", qc["word_count"])

r = c.put(f"/api/stories/{sid}", json={"title": "改名后的标题", "body": ""})
print("4) 改标题:", r.json()["title"])

r = c.post(f"/api/stories/{sid}/approve").json()
print("5) 批准入库:", r["ok"])

c.post(f"/api/stories/{sid}/status", json={"status": "published"})
rows = c.get("/api/stories").json()
print("6) 状态流转:", rows[0]["status"], rows[0]["published_at"])

txt = c.get(f"/api/stories/{sid}/export").text
print("7) 导出TXT:", txt[:20], "... 共", len(txt), "字符")

r = c.delete(f"/api/stories/{sid}")
print("8) 删除:", r.json())

# 9) 温情线：模板与数据链路
import prompts
mw = prompts.topic_messages(
    [{"main": "婚姻家庭", "plot": "破镜重圆", "emo": "先虐后甜",
      "core": "迟到的理解", "set": "旧物传信", "obj": "一台缝纫机"}],
    [], line="温情")
u = mw[1]["content"]
print("9) 温情选题模板:", len(mw) == 2 and "内核" in u and "意象" in u
      and "官方分类" in u)

ow = prompts.outline_messages({"title": "测试温情", "hook": "x", "line": "温情"})
print("10) 温情大纲模板:", "情绪法则" in ow[0]["content"] and "motif" in ow[1]["content"])

sw = {"title": "测试温情", "line": "温情",
      "outline": {"sections": [{"no": 1, "beats": ["a"], "hook": "b"}],
                  "characters": [], "narrator": "我", "clues": [],
                  "motif": {"object": "缝纫机", "plan": "一、二、五节各一次"},
                  "rules": "无"},
      "summaries": []}
msec = prompts.section_messages(sw, 1, 5)
print("11) 温情分节模板:", "情绪法则" in msec[0]["content"]
      and "核心意象" in msec[1]["content"])

mrev = prompts.review_messages("测试温情", "正文", line="温情")
print("12) 温情审稿模板:", "煽情" in mrev[1]["content"])

sid2 = db.create_story({"title": "测试温情线", "line": "温情"}, {"sections": []})
print("13) 稿件风格字段:", db.get_story(sid2)["line"])
c.delete(f"/api/stories/{sid2}")

# 14) 拆解库：存储、示例注入、模板
bid = db.add_bench("测试爆款标题", "开头。中间。结尾。", "悬疑")
db.save_bench_analysis(bid, {"title_formula": "第一人称+反常行为",
                             "opening_type": "反常物件",
                             "opening": "第一句抛物件，第二句给反常"})
ex = db.bench_examples("悬疑")
print("14) 拆解示例注入:", any(b["title"] == "测试爆款标题" for b in ex))

mb = prompts.bench_messages("测试爆款标题", "正文", "悬疑")
mr = prompts.bench_report_messages("摘要1\n摘要2", 2, "温情")
mt = prompts.topic_messages(
    [{"main": "婚姻家庭", "plot": "破镜重圆", "emo": "先虐后甜",
      "core": "迟到的理解", "set": "旧物传信", "obj": "缝纫机"}],
    [], line="温情",
    bench_titles=["测试爆款标题（第一人称+反常行为）"])
print("15) 拆解模板:", "title_formula" in mb[1]["content"]
      and "rules" in mr[1]["content"] and "禁止抄情节" in mt[1]["content"])

r = c.get("/api/bench").json()
print("16) 拆解接口:", len(r) >= 1, "|", r[0]["data"].get("title_formula"))
db.delete_bench(bid)

# 17) 官方分类池：抽样键完整、角色标签注入提示词、爽文口径
import random
import pools
rng = random.SystemRandom()
ps = pools.sample_combo(rng)
pw = pools.sample_warm_combo(rng)
ok17 = (set(ps) == {"main", "plot", "bg", "emo", "stance", "engine"}
        and set(pw) == {"main", "plot", "emo", "core", "set", "obj"})
mrole = prompts.topic_messages([ps], [], line="悬疑")[1]["content"]
print("17) 官方分类池抽样:", ok17,
      "| 爽文:", ps["main"], ps["plot"], ps["emo"],
      "| 写实:", pw["main"], pw["plot"], pw["emo"],
      "| 角色标签注入:", "白月光" in mrole and "狼人" in mrole,
      "| 清醒人设口径:", "人设" in mrole and "憋屈让读者受" in mrole)

# 18) 四线定位：爽感法则（悬疑）/ 情绪法则+白描（温情）/ 严谨法则（严谨）
print("18) 线定位:", "爽感法则" in prompts.SYS_WRITER
      and "无欲无求" in prompts.SYS_WRITER and "不内耗" in prompts.SYS_WRITER
      and "人间烟火" in prompts.SYS_WRITER_WARM and "白描" in prompts.SYS_WRITER_WARM
      and "严谨法则" in prompts.SYS_WRITER_RIGOR and "验算" in prompts.SYS_WRITER_RIGOR
      and "证据链" not in prompts.review_messages("t", "b", line="悬疑")[1]["content"]
      and pools.LINE_NAMES["悬疑"] == "无脑爽文")


# 19) 官方分类词表：粘贴解析 / 覆盖落盘 / 一键还原
import paths
dims, unknown = pools.parse_categories_raw(
    "<div>主分类</div><span>婚姻家庭</span>悬疑惊悚 情节：追妻火葬场、重生")
ok19 = (dims.get("主分类") == ["婚姻家庭", "悬疑惊悚"]
        and dims.get("情节") == ["追妻火葬场", "重生"] and not unknown)
f = paths.DATA_DIR / "categories.json"
if not f.exists():  # 已有自定义词表时不落盘，避免动真实配置
    pools.apply_cat_override({"主分类": ["婚姻家庭", "悬疑惊悚", "测试新增词"]})
    ok19 = ok19 and "测试新增词" in pools.CAT["主分类"] and f.exists()
    pools.reset_cat_override()
    ok19 = ok19 and "测试新增词" not in pools.CAT["主分类"] and not f.exists()
print("19) 分类词表解析/覆盖/恢复:", ok19)


# 20) 混合模式已整体移除（按线单独生成）
import inspect
import io
import generator
gsrc = inspect.getsource(generator.gen_topics)
html = io.open("static/index.html", encoding="utf-8").read()
ok20 = ("混合" not in gsrc and "混合" not in pools.LINE_NAMES
        and "混合" not in html
        and 'lbtn active" data-line="悬疑"' in html
        and "line: curLine" in html)
print("20) 混合模式移除:", ok20)

# 21) 信息源口子已预留：ingest.fetch 未实现时明确报错，/api/bench/import 路由在位
import ingest
try:
    ingest.fetch("test://x")
    ok21 = False
except NotImplementedError:
    ok21 = True
except Exception:
    ok21 = False
asrc = io.open("app.py", encoding="utf-8").read()
ok21 = ok21 and "/api/bench/import" in asrc and "import ingest" in asrc
print("21) 信息源口子已预留:", ok21)

# 22) JSON解析失败自动喂错重试一次 + 选题提示词中文引号铁律
import llm
_calls = []
_script = ["抱歉，这不是JSON",
           '[{"title": "示例选题", "hook": "他问’怎么了’"}]',
           '说明：[{"name": "路人"}]',
           '[{"title": "示例选题二", "hook": "她笑了"}]']
def _fake_chat(messages, **kw):
    _calls.append(list(messages))
    return _script[len(_calls) - 1]
_orig_chat = llm.chat
llm.chat = _fake_chat
try:
    dataA = llm.ask_json([{"role": "user", "content": "出选题"}],
                         log=lambda s: None, want_list=True, item_key="title")
    dataB = llm.ask_json([{"role": "user", "content": "再出"}],
                         log=lambda s: None, want_list=True, item_key="title")
finally:
    llm.chat = _orig_chat
psrc = io.open("prompts.py", encoding="utf-8").read()
ok22 = (len(_calls) == 4 and len(dataA) == 1 and dataA[0]["title"] == "示例选题"
        and dataB[0]["title"] == "示例选题二"
        and any("模型未返回有效JSON" in str(m.get("content", "")) for m in _calls[1])
        and any("缺少 title" in str(m.get("content", "")) for m in _calls[3])
        and len(_calls[1]) == 3 and len(_calls[3]) == 3
        and psrc.count("中文引号") >= 2)
print("22) JSON解析失败自动重试+中文引号铁律:", ok22)

# 23) extract_json 顶层形状保真：审稿对象不再被截成 issues 数组
r_obj = llm.extract_json('审稿结果如下：{"logic_score": 85, "hook_score": 70, "ai_risk": 30, "issues": [{"type": "节奏", "detail": "x", "where": "y"}]}')
r_arr = llm.extract_json('```json [{"title": "a"}, {"title": "b"}] ```')
r_pure = llm.extract_json('{"logic_score": 9, "issues": []}')
ok23 = (isinstance(r_obj, dict) and r_obj.get("logic_score") == 85 and len(r_obj.get("issues")) == 1
        and isinstance(r_arr, list) and len(r_arr) == 2 and r_arr[0].get("title") == "a"
        and isinstance(r_pure, dict) and r_pure.get("logic_score") == 9)
print("23) extract_json顶层形状保真:", ok23)

# 24) ask_json need_keys 校验：返回缺必需字段时喂回重试
_oc = llm.chat
_script2 = ['{"verdict": "好"}',
            '{"logic_score": 80, "hook_score": 70, "ai_risk": 20, "issues": []}']
_calls2 = []
def _fake_chat2(messages, **kw):
    _calls2.append(list(messages))
    return _script2[len(_calls2) - 1]
llm.chat = _fake_chat2
try:
    dataC = llm.ask_json([{"role": "user", "content": "审稿"}], log=lambda s: None,
                         need_keys=["logic_score", "hook_score", "ai_risk", "issues"])
finally:
    llm.chat = _oc
ok24 = (len(_calls2) == 2 and isinstance(dataC, dict) and dataC["logic_score"] == 80
        and any("缺少字段" in str(m.get("content", "")) for m in _calls2[1]))
print("24) 审稿JSON缺字段自动重试:", ok24)

# 25) 质量环：意见最高优先级 + 一轮通过自动入库（含事实核对两道QC）
import json as _json
sid25 = db.create_story(topic, outline)
db.update_story(sid25, body=body)
_calls25 = []
rev1 = '{"logic_score": 70, "hook_score": 65, "ai_risk": 30, "issues": [{"type": "底牌", "detail": "无铺垫", "where": "60%处"}]}'
facts25 = '{"facts": [{"item": "操盘年限", "value": "七年", "first_seen": "第1节", "source_span": "入市七年", "known_by": ["叙述者"], "used_at": ["第4节"]}]}'
logic25 = '{"issues": [], "uncertain": ["载重与车数关系建议人工复核"]}'
_script25 = [rev1, facts25, logic25,
             '{"facts": [{"fact": "操盘年限", "value": "七年", "where": "第一节"}]}'] + ["改后第" + m + "节正文" for m in ["一", "二", "三", "四", "五"]] + [
    '{"note_done": true, "problems": [{"where": "第二节", "detail": "过渡略生硬", "severity": "minor"}]}',
    '{"logic_score": 90, "hook_score": 75, "ai_risk": 15, "issues": []}']
def _fake25(messages, **kw):
    _calls25.append(list(messages))
    return _script25[len(_calls25) - 1]
_oc25 = llm.chat
llm.chat = _fake25
try:
    rep25 = generator.quality_loop(sid25, "把结尾改成开放式", log=lambda x: None)
finally:
    llm.chat = _orig_chat
rev_call = _calls25[4][1]["content"]
ok25 = (len(_calls25) == 11
        and rep25["audits"][0]["hard"] == 0
        and "把结尾改成开放式" in rev_call
        and rev_call.index("把结尾改成开放式") < rev_call.index("AI审稿问题清单")
        and "操盘年限" in _calls25[2][1]["content"]
        and rep25["verdict"] == "通过" and rep25["rounds"] == 1
        and rep25["fact_qc"]["skipped"] is False
        and rep25["fact_qc"]["uncertain"]
        and db.get_story(sid25)["status"] == "approved"
        and db.get_story(sid25)["note"] == "把结尾改成开放式"
        and "改后第五节正文" in db.get_story(sid25)["body"])
print("25) 质量环一轮通过+意见优先:", ok25)

# 26) 质量环：两轮校对不过 → 自动废弃并记录原因
sid26 = db.create_story(topic, outline)
db.update_story(sid26, body=body,
                review_json=_json.dumps({"logic_score": 60, "hook_score": 70,
                                         "ai_risk": 40,
                                         "issues": [{"type": "节奏", "detail": "拖", "where": "40%处"}]},
                                        ensure_ascii=False))
_calls26 = []
fail_audit = '{"note_done": false, "problems": [{"where": "结尾", "detail": "意见未落实", "severity": "block"}]}'
_script26 = ([facts25, logic25,
              '{"facts": [{"fact": "操盘年限", "value": "七年", "where": "第一节"}]}']
             + ["重写文本A"] * 5 + [fail_audit]
             + ["重写文本B"] * 5 + [fail_audit]
             + ['{"logic_score": 60, "hook_score": 40, "ai_risk": 50, "issues": []}'])
def _fake26(messages, **kw):
    _calls26.append(1)
    return _script26[len(_calls26) - 1]
llm.chat = _fake26
try:
    rep26 = generator.quality_loop(sid26, "压缩节奏", log=lambda x: None)
finally:
    llm.chat = _orig_chat
ok26 = (len(_calls26) == 16
        and rep26["verdict"] == "未过" and rep26["rounds"] == 2
        and len(rep26["audits"]) == 2
        and any("意见未落实" in r for r in rep26["reasons"])
        and db.get_story(sid26)["status"] == "rejected")
print("26) 质量环两轮不过自动废弃:", ok26)

# 27) 选题可重复写稿：used_count 递增、无“已使用”门禁（无Key任务报错不影响计数）
tid27 = db.add_topic("可重复选题测试", "钩子", line="悬疑")
c.post(f"/api/topics/{tid27}/write")
c.post(f"/api/topics/{tid27}/write")
time.sleep(1.0)  # 等后台任务自行失败（无Key），计数在启动前已完成
rows27 = {t["id"]: t for t in c.get("/api/topics").json()}
ok27 = (rows27[tid27]["used_count"] == 2 and rows27[tid27]["status"] == "used")
print("27) 选题重复使用+计数:", ok27)

# 28) 大纲→吸睛标题→写作：标题步改写书名、3候选存入 outline_json
_outline28 = {
    "characters": [{"name": "我", "role": "母亲", "secret": "孩子不是普通孩子"}],
    "narrator": "我是考生家长",
    "sections": [
        {"no": 1, "beats": ["反常开场"], "hook": "断章"},
        {"no": 2, "beats": ["冲突升级"], "hook": "断章"},
    ],
    "clues": [{"what": "准考证", "planted": "第1节", "payoff": "第2节"}],
    "final_line": "点题",
    "title_echo": "呼应",
}
_calls28 = []


def _fake28(messages, **kw):
    _calls28.append(list(messages))
    u = messages[-1]["content"] if messages else ""
    if "爆款标题样本" in u:
        return ('{"titles": [{"text": "我儿子才三岁，你说他高考作弊？", "why": "反差"},'
                ' {"text": "候选B", "why": "x"}, {"text": "候选C", "why": "y"}]}')
    if "围绕下面的选题" in u:
        return _json.dumps(_outline28, ensure_ascii=False)
    return "正文第一段。\n摘要：我赢了"


_orig_chat = llm.chat
llm.chat = _fake28
try:
    sid28 = generator.start_story({"title": "原始选题", "hook": "卖点",
                                   "line": "悬疑"}, log=lambda x: None)
finally:
    llm.chat = _orig_chat
s28 = db.get_story(sid28)
ok28 = (s28["title"] == "我儿子才三岁，你说他高考作弊？"
        and len(s28["outline"].get("title_options", [])) == 3
        and len(_calls28) == 4
        and any("爆款标题样本" in m[-1]["content"] and "我儿子才三岁" in m[-1]["content"]
                for m in _calls28)
        and any("【分节剧情】" in m[-1]["content"] for m in _calls28)
        and s28["status"] == "generated")
print("28) 大纲→标题→写作 流水线:", ok28)

# 29) 温情线合并人间烟火（吸收纯真笔触文笔）+ 严谨线细腻写实（强逻辑悬疑/无限流）
_t29w = {"title": "外婆的顶针", "hook": "小事", "line": "温情"}
_t29r = {"title": "死者手表慢了七分钟", "hook": "谜面", "line": "严谨"}
_o29 = {"sections": [{"no": 1, "beats": ["a"], "hook": "h"}],
        "characters": [], "clues": [], "narrator": "我"}
_or29 = {"sections": [{"no": 1, "beats": ["a"], "hook": "h"}],
         "characters": [], "clues": [], "narrator": "我",
         "rules": "每日凌晨副本刷新规则一条，违者抹杀"}
m29_topw = prompts.topic_messages(
    [{"main": "家庭亲情", "plot": "日常", "emo": "温暖",
      "core": "亏欠", "set": "无", "obj": "顶针"}], [], line="温情")
m29_topr = prompts.topic_messages(
    [{"main": "悬疑惊悚", "plot": "推理", "bg": "现代", "emo": "惊悚",
      "riddle": "现场干净得反常", "gimmick": "监控被删改的时间差",
      "stake": "破不了案，下一个就是我"}], [], line="严谨")
m29_outw = prompts.outline_messages(_t29w)
m29_outr = prompts.outline_messages(_t29r)
m29_secw = prompts.section_messages(
    {"title": "x", "line": "温情", "topic": {"line": "温情"},
     "outline": _o29, "summaries": []}, 1, 5)
m29_secr = prompts.section_messages(
    {"title": "x", "line": "严谨", "topic": {"line": "严谨"},
     "outline": _or29, "summaries": []}, 1, 5)
m29_rev = prompts.review_messages("x", "正文", line="温情")
m29_revr = prompts.review_messages("x", "正文", line="严谨")
m29_tt = prompts.title_messages(_t29w, _o29, line="温情")
m29_ttw = prompts.title_messages(_t29r, _o29, line="严谨")
m29_tts = prompts.title_messages(
    {"title": "x", "hook": "y", "line": "悬疑"}, _o29, line="悬疑")
usrc = io.open("static/index.html", encoding="utf-8").read()
ok29 = (pools.LINE_NAMES.get("温情") == "人间烟火"
    and pools.LINE_NAMES.get("严谨") == "细腻写实"
    and m29_topw[0]["content"] == prompts.SYS_TOPIC_WARM
    and "意象" in m29_topw[1]["content"] and "两段式" in m29_topw[1]["content"]
    and m29_topr[0]["content"] == prompts.SYS_TOPIC_RIGOR
    and "谜面" in m29_topr[1]["content"]
    and "死者手表慢了七分钟" in m29_topr[1]["content"]
    and m29_outw[0]["content"] == prompts.SYS_WRITER_WARM
    and "motif" in m29_outw[1]["content"]
    and "情绪压强" in m29_outw[1]["content"]
    and m29_outr[0]["content"] == prompts.SYS_WRITER_RIGOR
    and '"rules"' in m29_outr[1]["content"]
    and "严谨要求" in m29_outr[1]["content"]
    and m29_secw[0]["content"] == prompts.SYS_WRITER_WARM
    and "情绪法则" in m29_secw[1]["content"]
    and m29_secr[0]["content"] == prompts.SYS_WRITER_RIGOR
    and "规则全文" in m29_secr[1]["content"]
    and "严谨法则" in m29_secr[1]["content"]
    and m29_rev[0]["content"] == prompts.SYS_REVIEW_WARM
    and "煽情" in m29_rev[1]["content"]
    and m29_revr[0]["content"] == prompts.SYS_REVIEW_RIGOR
    and "logic_score" in m29_revr[1]["content"]
    and "我爸临终前说，我不是他亲生的" in m29_tt[1]["content"]
    and "两段式" in m29_tt[1]["content"]
    and "不玩猎奇反转" in m29_tt[1]["content"]
    and "死者手表慢了七分钟，我翻出了第三份口供" in m29_ttw[1]["content"]
    and "两段式" in m29_ttw[1]["content"]
    and "两段式" in m29_tts[1]["content"]
    and "我儿子才三岁" in m29_tts[1]["content"]
    and 'data-line="温情"' in usrc and 'data-line="严谨"' in usrc
    and "src-rigor" in usrc and "'严谨': '细腻写实'" in usrc
    and 'data-line="纯文"' not in usrc and "src-pure" not in usrc)
print("29) 温情=人间烟火+严谨=细腻写实:", ok29)

# 30) 标题统一两段式：三条线标题要求均含两段式，样本库全两段
banks30 = (prompts.TITLE_BANK_SUS + prompts.TITLE_BANK_WARM
           + prompts.TITLE_BANK_RIGOR + prompts.TITLE_BANK_FAN)
import re as _re
def _two_part(t):
    return bool(_re.search(r"[，,——？?！!]", t))
ok30 = (all("两段式" in m[1]["content"] for m in (m29_tt, m29_ttw, m29_tts))
    and all(_two_part(t) for t in banks30))
print("30) 标题两段式统一:", ok30)

# 31) 二创线：四类底座选题池+情怀反差口径贯通
import random as _random
c31 = pools.sample_fan_combo(_random.Random(1))
ok31 = (all(k in c31 for k in ("main", "base", "ip", "role", "twist", "emo"))
    and c31["base"] in pools.FAN_BASES
    and pools.LINE_NAMES.get("二创") == "二创改编")
_t31 = {"title": "穿成巡山小妖", "hook": "小妖掀桌", "line": "二创"}
m31_top = prompts.topic_messages([c31], [], line="二创")
m31_out = prompts.outline_messages(_t31)
m31_sec = prompts.section_messages(
    {"title": "x", "line": "二创", "topic": {"line": "二创"},
     "outline": _o29, "summaries": []}, 1, 5)
m31_rev = prompts.review_messages("x", "正文", line="二创")
m31_tt = prompts.title_messages(_t31, _o29, line="二创")
ok31 &= (m31_top[0]["content"] == prompts.SYS_TOPIC_FAN
    and "底座" in m31_top[1]["content"] and "两段式" in m31_top[1]["content"]
    and m31_out[0]["content"] == prompts.SYS_WRITER_FAN
    and "二创要求" in m31_out[1]["content"]
    and m31_sec[0]["content"] == prompts.SYS_WRITER_FAN
    and "二创铁律" in m31_sec[1]["content"]
    and m31_rev[0]["content"] == prompts.SYS_REVIEW_FAN
    and "考据" in m31_rev[1]["content"]
    and "穿成巡山小妖" in m31_tt[1]["content"]
    and "两段式" in m31_tt[1]["content"]
    and all(_two_part(t) for t in prompts.TITLE_BANK_FAN)
    and 'data-line="二创"' in usrc and "src-fan" in usrc
    and "'二创': '二创改编'" in usrc)
print("31) 二创线（二创改编）:", ok31)



# 32) 正文单换行：组装/保存/拆分全链路不再出现空行
sid32 = db.create_story({"title": "格式测试", "line": "悬疑"}, {})
db.append_section(sid32, 1, "第一段。\n\n\n第二段。", "一")
db.append_section(sid32, 2, "第三段。\n\n第四段。", "二")
s32 = db.get_story(sid32)
ok32 = (s32["body"] == "一\n第一段。\n第二段。\n二\n第三段。\n第四段。")
db.update_story(sid32, body="一\n\n老稿双换行\n\n二\n\n尾部")
s32 = db.get_story(sid32)
ok32 &= (s32["body"] == "一\n老稿双换行\n二\n尾部"
    and db.clean_text("a\r\n\r\nb") == "a\nb")
chunks32 = generator._split_body("一\n甲\n乙\n二\n丙")
ok32 &= (len(chunks32) == 2 and chunks32[0][0] == "一"
    and chunks32[1][0] == "二" and chunks32[1][1] == "丙")
db.delete_story(sid32)
print("32) 正文单换行格式:", ok32)

# 33) 事实核对QC：抽取→确定性交叉→逻辑审读，只报 issue 不改稿
import qc as _qc
ok33 = (_qc.parse_num("八万") == 80000 and _qc.parse_num("三万") == 30000
        and _qc.parse_num("3万") == 30000 and _qc.parse_num("一千五百") == 1500
        and _qc.parse_num("1,500") == 1500 and _qc.parse_num("26") == 26
        and _qc.parse_num("三千石") == 3000 and _qc.parse_num("7年") == 7
        and _qc.parse_num("三千五") == 3500 and _qc.parse_num("一百零五") == 105
        and _qc.parse_num("90人") == 90 and _qc.parse_num("百分之三十") == 30
        and _qc.parse_num("十几人") is None and _qc.parse_num("三十多万") is None
        and _qc.parse_num("他笑了笑") is None and _qc.parse_num("") is None)
_f33 = [
    {"item": "遇难人数", "value": "三万人", "first_seen": "第1节",
     "source_span": "三万人遇难", "known_by": ["叙述者"], "used_at": []},
    {"item": "遇难人数", "value": "八万人", "first_seen": "第1节",
     "source_span": "八万人失踪", "known_by": ["叙述者"], "used_at": []},
    {"item": "密信", "value": "一封", "first_seen": "第2节",
     "source_span": "抽屉里的密信", "known_by": ["林秋"], "used_at": ["第1节"]},
]
_issues33 = _qc.cross_check_facts(_f33)
ok33 &= (len(_issues33) == 2
         and "遇难人数" in _issues33[0] and "数值冲突" in _issues33[0]
         and "密信" in _issues33[1] and "信息穿越" in _issues33[1])
fm33 = prompts.fact_messages("核对", "正文")
lm33 = prompts.logic_review_messages("核对", "正文", "- 密信=一封")
ok33 &= (fm33[0]["content"] == prompts.SYS_FACT
         and "first_seen" in fm33[1]["content"]
         and "known_by" in fm33[1]["content"]
         and "used_at" in fm33[1]["content"]
         and lm33[0]["content"] == prompts.SYS_LOGIC
         and "数量级" in lm33[0]["content"]
         and "uncertain" in lm33[1]["content"])
_facts33 = _json.dumps({"facts": [
    {"item": "遇难人数", "value": "三万人", "first_seen": "第1节",
     "source_span": "三万人", "known_by": ["叙述者"], "used_at": []},
    {"item": "遇难人数", "value": "八万人", "first_seen": "第1节",
     "source_span": "八万人", "known_by": ["叙述者"], "used_at": []}]},
    ensure_ascii=False)
_logic33 = _json.dumps({"issues": [{"type": "数量级", "detail": "车数与总量对不上",
                                    "where": "第3节"}],
                        "uncertain": ["载重参数拿不准"]}, ensure_ascii=False)
_script33 = [_facts33, _logic33]
_calls33 = []
def _fake33(messages, **kw):
    _calls33.append(list(messages))
    return _script33[len(_calls33) - 1]
llm.chat = _fake33
try:
    fq33 = generator.fact_qc_story({"title": "核对", "body": "正文"},
                                   log=lambda x: None)
finally:
    llm.chat = _orig_chat
ok33 &= (fq33["skipped"] is False
         and len(fq33["issues"]) == 2
         and fq33["issues"][0]["type"] == "事实"
         and "数值冲突" in fq33["issues"][0]["detail"]
         and fq33["issues"][1]["type"] == "数量级"
         and fq33["uncertain"] == ["载重参数拿不准"]
         and len(_calls33) == 2
         and "遇难人数" in _calls33[1][1]["content"])
llm.chat = lambda m, **kw: "这不是JSON"
try:
    fq33b = generator.fact_qc_story({"title": "核对", "body": "正文"},
                                    log=lambda x: None)
finally:
    llm.chat = _orig_chat
ok33 &= (fq33b.get("skipped") is True
         and fq33b["issues"] == [] and fq33b["uncertain"] == [])
print("33) 事实核对QC（抽取→交叉→逻辑，只报不改）:", ok33)

# 34) 二创双模式 + 调味包 + 胜利成本：大纲/分节/审稿全链路注入（只定规则，不改稿）
import random as _rand
c34 = pools.sample_fan_combo(_rand.Random(11))
ok34 = c34["mode"] in ("gap", "butterfly")
ok34 &= generator._combo_text(c34).count("模式「") == 1
rng34 = _rand.Random(3)
rng34.random = lambda: 0.0
ok34 &= (pools.maybe_flavor(rng34, "悬疑") == "烟火落点"
         and pools.maybe_flavor(rng34, "严谨") == "烟火余味"
         and pools.maybe_flavor(rng34, "二创") == "严谨工程流"
         and pools.maybe_flavor(rng34, "温情") is None)
u34g = prompts.outline_messages(
    {"title": "t", "hook": "h", "line": "二创", "mode": "gap"})[1]["content"]
u34b = prompts.outline_messages(
    {"title": "t", "hook": "h", "line": "二创", "mode": "butterfly"})[1]["content"]
u34s = prompts.outline_messages(
    {"title": "t", "hook": "h", "line": "悬疑"})[1]["content"]
ok34 &= ("补空白模式" in u34g and "结局不变" in u34g
         and "蝴蝶效应模式" not in u34g
         and "蝴蝶效应模式" in u34b and "必须有因果" in u34b
         and "price_paid" in u34s and "永久失去了什么" in u34s
         and "填 none" in u34s)
sec34 = prompts.section_messages(
    {"title": "x", "line": "严谨", "topic": {"line": "严谨", "flavor": "烟火余味"},
     "outline": {"sections": [], "characters": [], "clues": []}}, 2, 5)
ok34 &= "调味包·烟火余味" in sec34[1]["content"]
rev34 = prompts.review_messages("x", "正文", "悬疑",
                                outline_note="胜利成本（大纲 price_paid）：none，因为……")
ok34 &= "大纲既定设定" in rev34[1]["content"]
top34 = prompts.topic_messages([dict(c34)], [], line="二创")
ok34 &= ("模式「" in top34[1]["content"]
         and pools.FAN_MODES[c34["mode"]] in top34[1]["content"])
print("34) 二创双模式+调味包+胜利成本:", ok34)

# 35) 表达倾向变体：每线 A/B 两套、随机抽取、写日志、存库、进分节 system
ok35 = all(len(pools.VARIANTS[l]) == 2 for l in ("悬疑", "温情", "严谨", "二创"))
ok35 &= len(pools.VARIANT_BY_NAME) == 8
r35 = _rand.Random(9)
ok35 &= {pools.sample_variant(r35, "悬疑")["key"] for _ in range(30)} == {"A", "B"}
_outline35 = {"sections": [{"no": 1, "beats": ["a"], "hook": "断章"}],
              "characters": [], "clues": []}
_calls35 = []
def _fake35(messages, **kw):
    _calls35.append(list(messages))
    u = messages[-1]["content"]
    if "围绕下面的选题" in u:
        return _json.dumps(_outline35, ensure_ascii=False)
    if "爆款标题样本" in u:
        return '{"titles": [{"text": "变体测试标题", "why": "x"}]}'
    return "正文。\n摘要：测"
llm.chat = _fake35
_logs35 = []
try:
    sid35 = generator.start_story({"title": "变体选题", "hook": "h", "line": "严谨"},
                                  log=_logs35.append)
finally:
    llm.chat = _orig_chat
s35 = db.get_story(sid35)
sec_calls35 = [c for c in _calls35 if "你正在写" in c[-1]["content"]]
ok35 &= (s35["variant"] in ("A·档案体", "B·贴身追凶")
         and any("本篇风格变体" in x for x in _logs35)
         and len(sec_calls35) == 1
         and "【本篇表达倾向：" in sec_calls35[0][0]["content"]
         and any(v["name"] in sec_calls35[0][0]["content"]
                 for v in pools.VARIANTS["严谨"]))
nosec35 = prompts.section_messages(
    {"title": "x", "line": "悬疑", "topic": {"line": "悬疑"},
     "outline": {"sections": [], "characters": [], "clues": []}}, 1, 5)
ok35 &= "本篇表达倾向" not in nosec35[0]["content"]
db.delete_story(sid35)
print("35) 表达倾向变体 A/B（随机+日志+存库）:", ok35)

# 36) 新功能界面可见：事实核对/待人工确认/风格变体/模式/调味都有渲染口
ok36 = ("[事实核对]" in usrc and "[待人工确认]" in usrc
        and "q.fact_qc" in usrc and "fq.skipped" in usrc
        and "风格变体" in usrc and "s.variant ?" in usrc
        and "FAN_MODE" in usrc and "调味·" in usrc
        and ".src-flavor{" in usrc)
print("36) 新功能界面可见:", ok36)

# 37) 稿件页改版：两栏布局 + 筛选/快捷操作 + 按状态收敛按钮 + 空稿清理
ok37 = ('.s-wrap{display:grid' in usrc and 'id="story-chips"' in usrc
        and "S_FILTERS" in usrc and "'pending'" in usrc
        and "renderEditorActions" in usrc and "cleanupEmpty" in usrc
        and "quickPublish" in usrc and "ed-loop" in usrc
        and "editor-empty" in usrc
        and "_pj(s.quality_json)" in usrc and "const _pj" in usrc
        and "stories-body" not in usrc
        and "scrollIntoView({behavior: 'smooth'})" not in usrc)
print("37) 稿件页两栏改版:", ok37)

# 38) 字数档位：随稿存库 → 分节提示词动态目标+字数下限+防注水；max_tokens 随篇幅
ok38 = (generator.WORD_TIERS == {"标准": 1500, "加长": 2100, "特长": 2800}
        and "全文五节共约6800字" not in open("prompts.py", encoding="utf-8").read())
st38 = {"title": "档位测试", "line": "悬疑",
        "outline": {"sections": [{"no": i, "beats": ["b"]} for i in range(1, 6)],
                    "characters": [], "clues": []}, "summaries": []}
st38["sec_words"] = 2100
m38 = prompts.section_messages(st38, 1, 5)[1]["content"]
ok38 = ok38 and ("本节约2100字" in m38 and "不得少于1785字" in m38
                 and "目标总字数约10500字" in m38 and "加长篇幅" in m38)
st38["sec_words"] = 0
m38b = prompts.section_messages(st38, 1, 5)[1]["content"]
ok38 = ok38 and ("本节约1350字" in m38b and "不得少于1147字" in m38b
                 and "加长篇幅" not in m38b)
sid38 = db.create_story({"title": "档位测试", "line": "悬疑"}, {}, sec_words=2100)
ok38 = ok38 and db.get_story(sid38)["sec_words"] == 2100
ok38 = ok38 and ("data-tier" in usrc and "setTier(this)" in usrc
                 and "tier: genTier" in usrc and "特长 1.1万+" in usrc
                 and "tierName" in usrc)
print("38) 字数档位:", ok38)

# 39) 稿件页流程可视化：流水线步骤条+质量证据+操作分层(cta/危险)+卡片进度线
ok39 = ('id="ed-pipe"' in usrc and "function renderPipe" in usrc
        and "PIPE_STEPS" in usrc and "PIPE_STAGE" in usrc
        and "质检·审核" in usrc and "renderPipe(s, qcRep, rvRep, quRep)" in usrc
        and "primary ed-cta" in usrc
        and "'ed-danger'" in usrc and "'ed-sub'" in usrc
        and "'AI审稿', 'ed-sub'" in usrc
        and "s-prog" in usrc and "流水线：① 生成" in usrc
        and "startQuality(), '下达意见·启动质量环', 'primary'" not in usrc)
print("39) 稿件页流程可视化:", ok39)

# 40) 审查结果独立右栏：整页三列（列表|正文|报告），空报告卡隐藏，显隐同步
ok40 = ('grid-template-columns:340px minmax(360px,1fr) minmax(280px,330px)' in usrc
        and 'class="s-reps"' in usrc and "审查结果" in usrc
        and ".s-reps>div:empty{display:none}" in usrc
        and "id=\"reps-empty\"" in usrc
        and "reps-empty').hidden" in usrc
        and "ed-bottom" not in usrc and "ed-reps" not in usrc)
print("40) 审查结果右栏三列布局:", ok40)
