# -*- coding: utf-8 -*-
"""市场情报抓取：通过发布助手浏览器（已登录）读取番茄作家后台的
灵感页——书荒热词榜（男频/女频 × 脑洞/传统）与热门故事，存入本地库。
只读页面内容，不做任何写操作。"""
import json
import subprocess
import time

import db
import paths

CDP_STATE = paths.DATA_DIR / "browser_cdp.json"
INSPIRATION_URL = ("https://fanqienovel.com/main/writer/inspiration"
                   "?enter_from=have_book&type=0")


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

_JS_STORIES = """() => {
  const out = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('a, [class*=title], [class*=name]')) {
    const t = (a.textContent || '').trim();
    if (t.length >= 6 && t.length <= 30 && /[\\u4e00-\\u9fa5]/.test(t)
        && !seen.has(t)) {
      seen.add(t);
      out.push(t);
    }
  }
  return out.slice(0, 30);
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


def scrape(log=print):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = _connect(p, log)
        try:
            ctx = br.contexts[0] if br.contexts else br.new_context()
            pg = ctx.new_page()
            log("打开灵感页（书荒热词榜）…")
            pg.goto(INSPIRATION_URL, wait_until="domcontentloaded")
            for _ in range(30):
                if pg.locator("text=书荒热词榜").count():
                    break
                pg.wait_for_timeout(1000)
            pg.wait_for_timeout(1500)

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

            stories = []
            if _click_text_js(pg, "热门故事"):
                pg.wait_for_timeout(2000)
                stories = pg.evaluate(_JS_STORIES) or []
                log(f"热门故事：{len(stories)} 条")
            try:
                pg.close()
            except Exception:
                pass
        finally:
            try:
                br.close()  # 只断开连接，不关浏览器
            except Exception:
                pass

    if rows:
        db.save_market_words(rows)
    if stories:
        db.save_market_stories(stories)
    log(f"✓ 已入库：热词 {len(rows)} 个，热门故事 {len(stories)} 条")
    return {"words": len(rows), "stories": len(stories)}
