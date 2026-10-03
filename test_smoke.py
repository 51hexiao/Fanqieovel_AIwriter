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

# 18) 双线定位改名：爽感法则 / 细腻写实
print("18) 线定位:", "爽感法则" in prompts.SYS_WRITER
      and "无欲无求" in prompts.SYS_WRITER and "不内耗" in prompts.SYS_WRITER
      and "细腻写实短篇" in prompts.SYS_WRITER_WARM
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

# 25) 质量环：意见最高优先级 + 一轮通过自动入库
import json as _json
sid25 = db.create_story(topic, outline)
db.update_story(sid25, body=body)
_calls25 = []
rev1 = '{"logic_score": 70, "hook_score": 65, "ai_risk": 30, "issues": [{"type": "底牌", "detail": "无铺垫", "where": "60%处"}]}'
_script25 = [rev1, '{"facts": [{"fact": "操盘年限", "value": "七年", "where": "第一节"}]}'] + ["改后第" + m + "节正文" for m in ["一", "二", "三", "四", "五"]] + [
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
rev_call = _calls25[2][1]["content"]
ok25 = (len(_calls25) == 9
        and rep25["audits"][0]["hard"] == 0
        and "把结尾改成开放式" in rev_call
        and rev_call.index("把结尾改成开放式") < rev_call.index("AI审稿问题清单")
        and rep25["verdict"] == "通过" and rep25["rounds"] == 1
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
_script26 = (['{"facts": [{"fact": "操盘年限", "value": "七年", "where": "第一节"}]}'] + ["重写文本A"] * 5 + [fail_audit]
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
ok26 = (len(_calls26) == 14
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
