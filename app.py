# -*- coding: utf-8 -*-
"""番茄短故事工作台 - 桌面版后端服务，由 desktop.py 以线程方式启动。"""
import json
import random
import threading
import time
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

import db
import bench as bench_mod
import generator
import ingest
import llm
import paths
import pools
import qc as qcmod

db.init()

app = FastAPI(title="番茄短故事工作台")
TASKS = {}


class StoryEdit(BaseModel):
    title: str = ""
    body: str = ""
    note: Optional[str] = None


class NoteIn(BaseModel):
    note: str = ""


class StatusIn(BaseModel):
    status: str


def start_task(kind, fn):
    tid = uuid.uuid4().hex[:8]
    TASKS[tid] = {"kind": kind, "status": "running", "stage": "准备中",
                  "log": [], "result": None, "error": None}

    def log(msg):
        t = TASKS[tid]
        t["log"].append(str(msg))
        t["stage"] = str(msg)

    def run():
        try:
            TASKS[tid]["result"] = fn(log)
            TASKS[tid]["status"] = "done"
        except Exception as e:
            TASKS[tid]["status"] = "error"
            TASKS[tid]["error"] = str(e)
            TASKS[tid]["log"].append("出错: " + str(e))

    threading.Thread(target=run, daemon=True).start()
    return {"task_id": tid}


@app.get("/api/tasks/{tid}")
def get_task(tid: str):
    return TASKS.get(tid, {"status": "unknown"})


# ---------- 配置 ----------
@app.get("/api/config")
def get_config():
    return llm.load()


@app.post("/api/config")
def set_config(payload: dict):
    allowed = {"api_base", "api_key", "model", "protocol", "writer_url",
               "temperature_write", "sec_words", "no_max_tokens", "timeout"}
    return llm.save({k: v for k, v in payload.items() if k in allowed})


@app.post("/api/config/test")
def test_config():
    ok, msg = llm.test_connection()
    return {"ok": ok, "msg": msg}


class ModelsIn(BaseModel):
    api_base: str = ""
    api_key: str = ""
    protocol: str = "openai"


@app.post("/api/models")
def list_models(b: ModelsIn):
    ok, msg, models = llm.list_models(b.api_base.strip(), b.api_key.strip(),
                                      b.protocol)
    return {"ok": ok, "msg": msg, "models": models}


# ---------- 选题 ----------
@app.get("/api/topics")
def get_topics(status: Optional[str] = None, line: Optional[str] = None):
    return db.list_topics(status, line)


@app.post("/api/topics/generate")
def gen_topics(payload: Optional[dict] = None):
    line = (payload or {}).get("line") or "悬疑"
    return start_task("topics",
                      lambda log: generator.gen_topics(log=log, line=line))


class TopicIn(BaseModel):
    title: str
    hook: str = ""
    social: str = ""
    diff: str = ""
    line: str = "悬疑"


@app.post("/api/topics")
def add_topic(b: TopicIn):
    if not b.title.strip():
        raise HTTPException(400, "选题内容不能为空")
    return {"ok": True,
            "id": db.add_topic(b.title.strip(), b.hook.strip(),
                               social=b.social.strip(), diff=b.diff.strip(),
                               line=b.line)}


@app.delete("/api/topics/{tid}")
def del_topic(tid: int):
    db.delete_topic(tid)
    return {"ok": True}


# ---------- 官方分类词表 ----------
@app.get("/api/categories")
def get_categories():
    return {"dims": pools.CAT, "overridden": pools.overridden_dims()}


@app.post("/api/categories/parse")
def parse_categories(payload: Optional[dict] = None):
    raw = (payload or {}).get("raw") or ""
    dims, unknown = pools.parse_categories_raw(raw)
    return {"dims": dims, "unknown": unknown}


@app.post("/api/categories/save")
def save_categories(payload: Optional[dict] = None):
    changed = pools.apply_cat_override((payload or {}).get("dims"))
    return {"ok": True, "changed": changed}


@app.post("/api/categories/reset")
def reset_categories():
    pools.reset_cat_override()
    return {"ok": True}


@app.post("/api/topics/{tid}/write")
def write_topic(tid: int, payload: Optional[dict] = None):
    topics = {t["id"]: t for t in db.list_topics()}
    topic = topics.get(tid)
    if not topic:
        raise HTTPException(404, "选题不存在")
    tier = ((payload or {}).get("tier") or "标准").strip()
    sw = generator.WORD_TIERS.get(tier, 0)
    db.use_topic(tid)
    return start_task("story", lambda log: generator.start_story(topic, log, sec_words=sw))


# ---------- 爆款拆解库 ----------
class BenchIn(BaseModel):
    title: str
    body: str = ""
    line: str = "悬疑"


@app.post("/api/bench")
def add_bench(b: BenchIn):
    if not b.title.strip() or not b.body.strip():
        raise HTTPException(400, "标题和正文都要填")
    return start_task("bench", lambda log: bench_mod.disassemble_new(
        b.title.strip(), b.body.strip(), b.line, log))


@app.post("/api/bench/import")
def import_bench(payload: Optional[dict] = None):
    """预留口子：信息源接入后（ingest.py 实现 fetch），链接导入自动走同一条拆解流程。"""
    url = ((payload or {}).get("url") or "").strip()
    if not url:
        raise HTTPException(400, "缺少 url")
    try:
        item = ingest.fetch(url)
    except NotImplementedError:
        raise HTTPException(501, "信息源未接入：番茄短故事网页端暂无阅读入口，现阶段请在「拆解」页手动粘贴")
    title = (item.get("title") or "").strip()
    body = (item.get("body") or "").strip()
    if not title or not body:
        raise HTTPException(400, "信息源返回的内容不完整（需要 title 和 body）")
    line = item.get("line") or "悬疑"
    return start_task("bench", lambda log: bench_mod.disassemble_new(title, body, line, log))


@app.get("/api/bench")
def list_bench(line: Optional[str] = None):
    return db.list_bench(line)


@app.delete("/api/bench/{bid}")
def del_bench(bid: int):
    db.delete_bench(bid)
    return {"ok": True}


@app.get("/api/bench/report")
def get_bench_report(line: str = "悬疑"):
    return {"line": line, "report": db.get_bench_report(line)}


@app.post("/api/bench/report")
def make_bench_report(payload: Optional[dict] = None):
    line = (payload or {}).get("line") or "悬疑"
    return start_task("report", lambda log: bench_mod.build_report(line, log))


# ---------- 稿件 ----------
@app.get("/api/stories")
def get_stories():
    return db.list_stories()


@app.get("/api/stories/{sid}")
def get_story(sid: int):
    s = db.get_story(sid)
    if not s:
        raise HTTPException(404, "稿件不存在")
    return s


@app.put("/api/stories/{sid}")
def edit_story(sid: int, e: StoryEdit):
    if not db.get_story(sid):
        raise HTTPException(404, "稿件不存在")
    fields = {}
    if e.title:
        fields["title"] = e.title
    if e.body:
        fields["body"] = e.body
    if e.note is not None:
        fields["note"] = e.note
    if fields:
        db.update_story(sid, **fields)
    return db.get_story(sid)


@app.delete("/api/stories/{sid}")
def del_story(sid: int):
    db.delete_story(sid)
    return {"ok": True}


@app.post("/api/stories/{sid}/qc")
def run_qc(sid: int):
    s = db.get_story(sid)
    if not s:
        raise HTTPException(404, "稿件不存在")
    report = qcmod.local_qc(s)
    db.update_story(sid, qc_json=json.dumps(report, ensure_ascii=False))
    return report


@app.post("/api/stories/{sid}/review")
def run_review(sid: int):
    if not db.get_story(sid):
        raise HTTPException(404, "稿件不存在")
    return start_task("review", lambda log: generator.review_story(sid, log))


@app.post("/api/stories/{sid}/polish")
def run_polish(sid: int):
    if not db.get_story(sid):
        raise HTTPException(404, "稿件不存在")
    return start_task("polish", lambda log: generator.polish_story(sid, log))


@app.post("/api/stories/{sid}/approve")
def approve(sid: int):
    s = db.get_story(sid)
    if not s:
        raise HTTPException(404, "稿件不存在")
    db.update_story(sid, status="approved")
    return {"ok": True}


@app.post("/api/stories/{sid}/status")
def set_status(sid: int, b: StatusIn):
    if not db.get_story(sid):
        raise HTTPException(404, "稿件不存在")
    if b.status == "published":
        db.update_story(sid, status=b.status, published_at=db.now())
    else:
        db.update_story(sid, status=b.status)
    return {"ok": True}


@app.post("/api/stories/{sid}/quality-loop")
def start_quality(sid: int, b: NoteIn):
    if not db.get_story(sid):
        raise HTTPException(404, "稿件不存在")
    return start_task("quality", lambda log: generator.quality_loop(sid, b.note, log))


MANAGE_URL = "https://fanqienovel.com/main/writer/short-manage"


def _human_pause(pg, lo=0.4, hi=1.2):
    """自然停顿：所有关键动作之间留真人节奏的随机间隔。"""
    pg.wait_for_timeout(int(random.uniform(lo, hi) * 1000))


def _human_click(pg, loc):
    """带鼠标轨迹的点击：先移到附近，再分步移到目标随机点按下。
    失败（取不到坐标等）退回普通点击。"""
    try:
        loc.scroll_into_view_if_needed(timeout=3000)
        box = loc.bounding_box()
        vp = pg.viewport_size
        if box and vp:
            tx = min(max(box["x"] + box["width"] * random.uniform(0.35, 0.65), 8),
                     vp["width"] - 8)
            ty = min(max(box["y"] + box["height"] * random.uniform(0.35, 0.65), 8),
                     vp["height"] - 8)
            pg.mouse.move(max(8, tx + random.uniform(-180, -60)),
                          max(8, ty + random.uniform(40, 130)))
            pg.wait_for_timeout(random.randint(90, 220))
            pg.mouse.move(tx, ty, steps=random.randint(6, 14))
            pg.wait_for_timeout(random.randint(60, 180))
            pg.mouse.click(tx, ty)
            return
    except Exception:
        pass
    loc.click()


def _visible(loc):
    try:
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def _pick_body(ed):
    """正文编辑器：取页面上最高的 contenteditable 区块（标题矮、正文高）。"""
    cands = ed.locator('[contenteditable="true"]')
    best, best_h = None, -1
    for i in range(cands.count()):
        try:
            box = cands.nth(i).bounding_box()
            if box and box["height"] > best_h:
                best, best_h = cands.nth(i), box["height"]
        except Exception:
            pass
    return best if best is not None else ed.locator("textarea").first


def _auto_draft(ctx, page, s, log):
    sel_path = paths.DATA_DIR / "selectors.json"
    sel = {}
    if sel_path.exists():
        try:
            sel = json.loads(sel_path.read_text(encoding="utf-8"))
        except Exception:
            sel = {}

    # 1) 打开管理页；未登录会跳登录页——期间绝不自动跳转，静默等用户登录
    log("打开短故事管理页…")
    page.goto(MANAGE_URL, wait_until="domcontentloaded")
    new_btn, i, logged_hint = None, 0, False
    deadline = time.time() + 600
    while time.time() < deadline:
        for pg in ctx.pages:
            if "short-manage" not in pg.url:
                continue
            cand = (pg.locator(sel["new_story_button"]) if sel.get("new_story_button")
                    else pg.get_by_text("新建短故事"))
            if _visible(cand):
                new_btn = cand.first
                break
        if new_btn is not None:
            break
        on_login = any("/writer/login" in (pg.url or "") or "passport" in (pg.url or "")
                       for pg in ctx.pages)
        if on_login:
            if not logged_hint:
                log("检测到登录页：请在发布助手浏览器里完成登录（验证码/扫码都行）。"
                    "输入过程不会被打断；登录状态保存在本机，下次发布免登录。")
            logged_hint = True
        elif i % 8 == 7:
            # 已登录但被跳到别页：定时回管理页（登录页绝不回跳，避免清掉用户输入）
            try:
                page.goto(MANAGE_URL, wait_until="domcontentloaded")
            except Exception:
                pass
        i += 1
        page.wait_for_timeout(2000)
    if new_btn is None:
        raise RuntimeError("10 分钟内未检测到「新建短故事」按钮，请确认已登录后重试")

    # 2) 新建 → 编辑页（同页跳转或新标签都兼容）
    log("点击「新建短故事」…")
    _human_click(page, new_btn)
    editor = None
    deadline = time.time() + 60
    while time.time() < deadline:
        for pg in ctx.pages:
            if "publish-short" in pg.url:
                editor = pg
                break
        if editor is not None:
            break
        page.wait_for_timeout(1000)
    if editor is None:
        raise RuntimeError("未能进入短故事编辑页，请在浏览器里手动操作")
    editor.bring_to_front()
    editor.wait_for_load_state("domcontentloaded")
    _human_pause(editor, 1.5, 2.6)

    # 3) 标题：直接对标题框逐字输入（不依赖全局焦点），回读校验，失败兜底 fill
    log("填入标题…")
    title_loc = (editor.locator(sel["title_input"]) if sel.get("title_input")
                 else editor.get_by_placeholder("短故事名称"))
    if not _visible(title_loc):
        title_loc = editor.locator(
            '[placeholder*="名称"], [aria-placeholder*="名称"], [data-placeholder*="名称"]')
    tloc = title_loc.first
    _human_click(editor, tloc)
    _human_pause(editor, 0.3, 0.8)
    try:
        tloc.fill("")  # 清掉此前误落进来的字符，防重复
    except Exception:
        pass
    try:
        tloc.press_sequentially(s["title"], delay=random.randint(80, 140))
    except Exception:
        editor.keyboard.type(s["title"], delay=random.randint(80, 140))
    got = ""
    for _ in range(5):
        try:
            got = tloc.input_value()
        except Exception:
            try:
                got = tloc.inner_text()
            except Exception:
                got = ""
        if (got or "").strip():
            break
        editor.wait_for_timeout(400)
    if s["title"] not in (got or ""):
        try:
            tloc.fill(s["title"])
            log("标题逐字输入未落到标题框，已改用直接填充并校验")
        except Exception:
            log("⚠ 标题可能没有填上，请在浏览器里手动补一下")
    else:
        log("✓ 标题已填入并回读校验")

    # 4) 正文走剪贴板粘贴，兼容富文本编辑器
    log(f"粘贴正文（约 {s['word_count']} 字）…")
    body_loc = (editor.locator(sel["editor"]) if sel.get("editor")
                else _pick_body(editor))
    _human_pause(editor, 0.5, 1.2)
    import pyperclip
    pyperclip.copy(db.clean_text(s["body"]))
    _human_click(editor, body_loc.first)
    editor.keyboard.press("Control+a")
    _human_pause(editor, 0.2, 0.5)
    editor.keyboard.press("Control+v")
    editor.wait_for_timeout(1500 + random.randint(0, 800))

    # 4.5) 封面：优先用平台自带的模板/随机封面入口（不代传图片）
    cover_done = False
    for key in ("随机封面", "模板封面", "智能封面", "生成封面", "一键生成", "换一批"):
        try:
            cand = editor.get_by_text(key)
            if cand.count() and _visible(cand.first):
                _human_click(editor, cand.first)
                editor.wait_for_timeout(1500 + random.randint(0, 800))
                cover_done = True
                log(f"✓ 封面：已用平台自带「{key}」生成，可在页面里换")
                break
        except Exception:
            continue
    if not cover_done:
        log("封面：页面上没找到自动生成入口，留给你手动选一张（工作台不代传图片）")

    # 4.6) 勾选项：声明类（原创/承诺/同意…）自动勾；分类按风格线匹配，最多勾一项
    line = (s.get("line") or "").strip()
    line_map = {"悬疑": ["悬疑"], "温情": ["温情", "情感", "人间"],
                "严谨": ["写实", "现实", "细腻"], "二创": ["二创", "同人", "改编"]}
    line_keys = line_map.get(line, [line] if line else [])
    decl_keys = ("原创", "承诺", "同意", "已阅读", "遵守")
    checked, picked = 0, []
    try:
        labels = editor.locator("label")
        for idx in range(labels.count()):
            lbl = labels.nth(idx)
            try:
                txt = (lbl.inner_text() or "").strip().replace(chr(10), " ")
            except Exception:
                continue
            if not txt or len(txt) > 60:
                continue
            try:
                if lbl.locator("input:checked").count():
                    continue
            except Exception:
                pass
            hit = None
            if any(k in txt for k in decl_keys):
                hit = "声明"
            elif line_keys and any(k in txt for k in line_keys):
                hit = "分类"
            if not hit:
                continue
            try:
                _human_click(editor, lbl)
                checked += 1
                picked.append(f"{hit}·{txt[:16]}")
                _human_pause(editor, 0.2, 0.5)
                if hit == "分类":
                    line_keys = []  # 分类一般单选，勾一项就收手
            except Exception:
                continue
    except Exception:
        pass
    if checked:
        log(f"✓ 自动勾选 {checked} 项：{'、'.join(picked[:4])}{'…' if len(picked) > 4 else ''}")
    else:
        log("勾选项：没匹配到可自动勾的声明/分类，留给你手动勾")

    # 5) 存草稿（发布按钮永远留给用户人工点击）
    log("点击「存草稿」…")
    save_btn = (editor.locator(sel["save_draft"]) if sel.get("save_draft")
                else editor.get_by_text("存草稿"))
    _human_pause(editor, 0.6, 1.4)
    _human_click(editor, save_btn.first)
    saved = False
    for _ in range(20):
        if _visible(editor.get_by_text("已保存")):
            saved = True
            break
        editor.wait_for_timeout(1000)
    log("✓ 草稿已保存：请在页面里确认封面/分类/选项，无误后自己点「发布」" if saved
        else "已点击存草稿（未捕捉到保存状态，请在浏览器里确认一下）")


CDP_STATE = paths.DATA_DIR / "browser_cdp.json"


def _cdp_alive(port):
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=1.5):
            return True
    except Exception:
        return False


def _find_local_browser():
    import os
    import shutil
    cands = [shutil.which("msedge"), shutil.which("chrome"),
             os.path.join(os.environ.get("ProgramFiles(x86)", "") or "",
                          r"Microsoft\Edge\Application\msedge.exe"),
             os.path.join(os.environ.get("ProgramFiles", "") or "",
                          r"Microsoft\Edge\Application\msedge.exe")]
    return next((c for c in cands if c and os.path.exists(c)), None)


def _open_writer_browser(sid, log):
    """发布助手用常驻浏览器：独立配置目录 + 调试端口，任务只连接不关闭。
    首次由工作台拉起，之后每次发布直接复用已打开、已登录的同一窗口。"""
    s = db.get_story(sid)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("未安装 playwright，发布助手不可用；可手动打开后台粘贴发布")
    port = 9333
    if CDP_STATE.exists():
        try:
            port = int(json.loads(CDP_STATE.read_text(encoding="utf-8"))["port"])
        except Exception:
            pass
    with sync_playwright() as p:
        browser = None
        if _cdp_alive(port):
            try:
                browser = p.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{port}", timeout=8000)
                log("已连接常驻发布助手浏览器（复用同一窗口与登录）")
            except Exception:
                browser = None
        if browser is None:
            exe = _find_local_browser()
            if not exe:
                raise RuntimeError("未找到 Edge/Chrome，无法启动发布助手浏览器")
            import subprocess
            subprocess.Popen([exe, f"--remote-debugging-port={port}",
                              f"--user-data-dir={paths.DATA_DIR / 'browser_profile'}",
                              "--no-first-run", "--no-default-browser-check",
                              "about:blank"])
            for _ in range(40):
                if _cdp_alive(port):
                    break
                time.sleep(0.5)
            if not _cdp_alive(port):
                raise RuntimeError("发布助手浏览器启动失败，请重试或手动打开后台粘贴发布")
            browser = p.chromium.connect_over_cdp(
                f"http://127.0.0.1:{port}", timeout=8000)
            CDP_STATE.write_text(json.dumps({"port": port}), encoding="utf-8")
            log("发布助手浏览器已启动（常驻）：首次使用请在这里登录一次番茄账号，"
                "登录保存在本机，窗口不关、下次免登录")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _auto_draft(ctx, page, s, log)
            log("浏览器保持打开（常驻）：完成封面/分类并人工发布后，回工作台点「标记已发布」")
        finally:
            try:
                browser.close()  # 仅断开工作台与浏览器的连接，不关闭浏览器窗口
            except Exception:
                pass
    return True


@app.post("/api/stories/{sid}/publish")
def publish(sid: int):
    if not db.get_story(sid):
        raise HTTPException(404, "稿件不存在")
    return start_task("publish", lambda log: _open_writer_browser(sid, log))


@app.post("/api/stories/{sid}/copy/{part}")
def copy_part(sid: int, part: str):
    s = db.get_story(sid)
    if not s:
        raise HTTPException(404, "稿件不存在")
    if part not in ("title", "body"):
        raise HTTPException(400, "part 必须是 title 或 body")
    text = s["title"] if part == "title" else db.clean_text(s["body"])
    if not (text or "").strip():
        raise HTTPException(400, "内容为空")
    import pyperclip
    pyperclip.copy(text)
    return {"ok": True, "len": len(text)}


@app.get("/api/stories/{sid}/export")
def export(sid: int):
    s = db.get_story(sid)
    if not s:
        raise HTTPException(404, "稿件不存在")
    txt = f"{s['title']}\n\n{s['body']}"
    return Response(txt, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition":
                             f"attachment; filename=story_{sid}.txt"})


@app.get("/")
def home():
    return FileResponse(paths.ASSETS_DIR / "static" / "index.html")
