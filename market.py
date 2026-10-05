# -*- coding: utf-8 -*-
"""市场情报抓取：通过发布助手浏览器（已登录）读取番茄作家后台的
灵感页——书荒热词榜（男频/女频 × 脑洞/传统）、主编力签（编辑求稿方向）
与热门故事（含题材标签，全部/黑马飙升/经典高热三个子榜），存入本地库。
只读页面内容，不做任何写操作。
（原创作品榜的标题做了字体反爬，抓出来是乱码，故不抓。）"""
import json
import subprocess
import time

import db
import paths

CDP_STATE = paths.DATA_DIR / "browser_cdp.json"
BASE_URL = "https://fanqienovel.com/main/writer/inspiration?enter_from=have_book"
INSPIRATION_URL = BASE_URL + "&type=0"


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


def _load_port():
    if CDP_STATE.exists():
        try:
            return int(json.loads(
                CDP_STATE.read_text(encoding="utf-8"))["port"])
        except Exception:
            pass
    return 9333


def _connect(p, log):
    """连上常驻助手浏览器；不在就拉起（与发布助手同一份配置，登录互通）。"""
    port = _load_port()
    if _cdp_alive(port):
        try:
            return p.chromium.connect_over_cdp(
                f"http://127.0.0.1:{port}", timeout=10000)
        except Exception:
            pass
    exe = _find_local_browser()
    if not exe:
        raise RuntimeError("未找到 Edge/Chrome，无法启动助手浏览器抓取市场数据")
    subprocess.Popen([exe, f"--remote-debugging-port={port}",
                      f"--user-data-dir={paths.DATA_DIR / 'browser_profile'}",
                      "--no-first-run", "--no-default-browser-check",
                      "about:blank"])
    for _ in range(40):
        if _cdp_alive(port):
            break
        time.sleep(0.5)
    if not _cdp_alive(port):
        raise RuntimeError("助手浏览器启动失败")
    CDP_STATE.write_text(json.dumps({"port": port}), encoding="utf-8")
    log("已拉起助手浏览器（与发布助手同配置）")
    return p.chromium.connect_over_cdp(
        f"http://127.0.0.1:{port}", timeout=10000)


_JS_BOARD = """() => {
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('div,li,a,span')) {
    const t = (el.textContent || '').trim();
    if (el.children.length || !/^0?\\d{1,2}$/.test(t)) continue;
    let row = el.parentElement;
    for (let i = 0; i < 4 && row; i++) {
      const rt = (row.textContent || '').replace(/\\s+/g, ' ').trim();
      const m = rt.match(
        /^(0?\\d{1,2})\\s*(新|▲\\s*\\d+|▼\\s*\\d+|-)?\\s*([\\u4e00-\\u9fa5A-Za-z0-9·]{2,10})\\s*$/);
      if (m && m[3] && !['男频', '女频', '脑洞', '传统'].includes(m[3])) {
        const sig = m[1] + '|' + m[3];
        if (!seen.has(sig)) {
          seen.add(sig);
          out.push({rank: parseInt(m[1], 10),
                    trend: (m[2] || '').replace(/\\s+/g, ''), word: m[3]});
        }
        break;
      }
      row = row.parentElement;
    }
  }
  return out;
}"""

_JS_PICKS = """() => {
  const out = [];
  const seen = new Set();
  for (const t of document.querySelectorAll(
      '[class*=recommend-item-content-title]:not([class*=title-tag])')) {
    const title = [...t.childNodes].filter(n => n.nodeType === 3)
      .map(n => n.textContent || '').join(' ').trim();
    if (!title || seen.has(title)) continue;
    seen.add(title);
    let box = t.parentElement, pitch = '', desc = '';
    for (let i = 0; i < 6 && box; i++) {
      const e = box.querySelector('[class*=content-edit]');
      const d = box.querySelector('[class*=content-desc]');
      if (e || d) {
        pitch = e ? (e.textContent || '').trim() : '';
        desc = d ? (d.textContent || '').trim() : '';
        break;
      }
      box = box.parentElement;
    }
    out.push({title, pitch, desc});
  }
  return out.slice(0, 12);
}"""

_JS_STORIES = """() => {
  const out = [];
  const seen = new Set();
  for (const card of document.querySelectorAll('[class*=hot-story-card]')) {
    const q = (s) => card.querySelector(s);
    const t = q('[class*=__title]');
    if (!t) continue;
    const title = (t.textContent || '').trim();
    if (!title || seen.has(title)) continue;
    seen.add(title);
    const a = q('[class*=__author]');
    const b = q('[class*=__brief]');
    const c = q('[class*=__category]');
    const w = q('[class*=__word-number]');
    out.push({title,
              author: a ? (a.textContent || '').trim() : '',
              brief: b ? (b.textContent || '').trim().slice(0, 150) : '',
              cats: c ? (c.textContent || '').trim() : '',
              words: w ? (w.textContent || '').trim() : ''});
  }
  return out.slice(0, 40);
}"""


def _click_text_js(pg, txt):
    return pg.evaluate("""(txt) => {
      const el = [...document.querySelectorAll('div,span,button,li')]
        .find(e => e.children.length === 0 &&
                   (e.textContent || '').trim() === txt &&
                   e.offsetParent !== null);
      if (!el) return false;
      el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      return true;
    }""", txt)


def _wait_render(pg, selector, timeout_s=15):
    """等 SPA 内容真正渲染出来（固定 sleep 会撞上没渲染完）。"""
    for _ in range(int(timeout_s * 2)):
        try:
            if pg.locator(selector).count():
                return True
        except Exception:
            pass
        pg.wait_for_timeout(500)
    return False


def scrape(log=print):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = _connect(p, log)
        try:
            ctx = br.contexts[0] if br.contexts else br.new_context()
            pg = ctx.new_page()
            log("打开灵感页（书荒热词榜）…")
            pg.goto(INSPIRATION_URL, wait_until="domcontentloaded")
            for _ in range(15):
                if "/writer/login" not in pg.url and "passport" not in pg.url:
                    break
                pg.wait_for_timeout(1000)
            if "/writer/login" in pg.url or "passport" in pg.url:
                raise RuntimeError(
                    "助手浏览器登录已过期：请在打开的浏览器窗口里重新登录番茄账号"
                    "（验证码自己输），然后再点「抓取」")
            if not _wait_render(pg, "text=书荒热词榜", 30):
                log("⚠ 灵感页加载异常，热词榜可能为空")

            rows = []
            for board in ("男频", "女频"):
                if not _click_text_js(pg, board):
                    log(f"⚠ 没找到「{board}」切换，跳过")
                    continue
                pg.wait_for_timeout(1200)
                for kind in ("脑洞", "传统"):
                    if _click_text_js(pg, kind):
                        pg.wait_for_timeout(1400)
                    got = pg.evaluate(_JS_BOARD) or []
                    for r in got:
                        r["board"], r["kind"] = board, kind
                    rows.extend(got)
                    log(f"{board}·{kind}：{len(got)} 词")
            pg.wait_for_timeout(500)

            picks = []
            log("打开灵感页（主编力签）…")
            pg.goto(BASE_URL + "&type=2", wait_until="domcontentloaded")
            if _wait_render(pg, "[class*=recommend-item-content-title]"):
                for board in ("男频", "女频"):
                    if not _click_text_js(pg, board):
                        log(f"⚠ 力签没找到「{board}」切换，跳过")
                        continue
                    pg.wait_for_timeout(1200)
                    for kind in ("脑洞", "传统"):
                        if _click_text_js(pg, kind):
                            pg.wait_for_timeout(1400)
                        got = pg.evaluate(_JS_PICKS) or []
                        for g in got:
                            g["board"], g["kind"] = board, kind
                        seen_t = {p["title"] for p in picks}
                        picks.extend(g for g in got if g["title"] not in seen_t)
                        log(f"力签·{board}·{kind}：{len(got)} 条")
            else:
                log("⚠ 主编力签内容没渲染出来，本次为空")

            stories = []
            log("打开灵感页（热门故事）…")
            pg.goto(BASE_URL + "&type=3", wait_until="domcontentloaded")
            if _wait_render(pg, "[class*=hot-story-card]"):
                for sub in ("全部", "黑马飙升", "经典高热"):
                    if not _click_text_js(pg, sub):
                        log(f"⚠ 没找到子榜「{sub}」，跳过")
                        continue
                    pg.wait_for_timeout(1800)
                    got = pg.evaluate(_JS_STORIES) or []
                    for g in got:
                        g["subtab"] = sub
                    seen_t = {g["title"] for g in stories}
                    stories.extend(g for g in got if g["title"] not in seen_t)
                    log(f"热门故事·{sub}：{len(got)} 条")
            else:
                log("⚠ 热门故事内容没渲染出来，本次为空")
            try:
                pg.close()
            except Exception:
                pass
        finally:
            try:
                br.close()  # 只断开连接，不关浏览器
            except Exception:
                pass

    db.save_market_words(rows)
    db.save_market_picks(picks)
    db.save_market_stories(stories)
    log(f"✓ 已入库：热词 {len(rows)} 个，主编力签 {len(picks)} 条，"
        f"热门故事 {len(stories)} 条")
    return {"words": len(rows), "picks": len(picks), "stories": len(stories)}
