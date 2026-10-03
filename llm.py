# -*- coding: utf-8 -*-
"""模型调用与本地配置。支持两种接口协议：
- openai：OpenAI 兼容 /chat/completions（智谱、DeepSeek、通义、各类中转）
- gemini：Google Gemini 原生 generateContent
所有对外报错都转成人话，不向上抛堆栈。"""
import json
import re
import time

import httpx

import paths

CONFIG = paths.DATA_DIR / "config.json"

DEFAULTS = {
    "api_base": "https://open.bigmodel.cn/api/paas/v4",
    "api_key": "",
    "model": "glm-4.6",
    "protocol": "openai",
    "temperature_write": 0.85,
    "writer_url": "https://fanqienovel.com/writer",
    "sec_words": 1350,
    "no_max_tokens": False,
    "timeout": 300,
}


def load():
    cfg = dict(DEFAULTS)
    if CONFIG.exists():
        try:
            cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save(new):
    cfg = load()
    cfg.update(new)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return cfg


def cfg(key, default=None):
    return load().get(key, default)


def _friendly(e):
    """把网络/接口异常翻译成用户能懂的话。"""
    if isinstance(e, httpx.ConnectError):
        return "无法连接 API 地址：检查地址和端口，确认服务已启动"
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code in (401, 403):
            return "鉴权失败：API Key 无效或没有权限"
        if code == 404:
            return ("接口路径不存在：检查 API 地址结尾"
                    "（OpenAI 兼容地址一般以 /v1 结尾）")
        if code == 429:
            return "触发限流或额度不足：稍后再试"
        return f"接口返回 {code}：{e.response.text[:150]}"
    if isinstance(e, httpx.TimeoutException):
        return "请求超时：网络慢或服务无响应，可稍后重试"
    return str(e)


def _timeout(c):
    try:
        return int(c.get("timeout") or 300)
    except Exception:
        return 300


def _is_local(url):
    try:
        host = httpx.URL(url).host or ""
    except Exception:
        return False
    return host in ("127.0.0.1", "localhost", "::1") or host.endswith(".local")


def _post(url, **kw):
    # 本机地址绕过系统代理，避免被代理拦成 502
    with httpx.Client(trust_env=not _is_local(url)) as cli:
        return cli.post(url, **kw)


def _get(url, **kw):
    with httpx.Client(trust_env=not _is_local(url)) as cli:
        return cli.get(url, **kw)


def _chat_openai(c, messages, temp, max_tokens):
    def go():
        body = {"model": c["model"], "messages": messages,
                "temperature": temp}
        if not c.get("no_max_tokens"):
            body["max_tokens"] = max_tokens
        r = _post(c["api_base"].rstrip("/") + "/chat/completions",
                  json=body,
                  headers={"Authorization": "Bearer " + c["api_key"]},
                  timeout=_timeout(c))
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    return go


def _chat_gemini(c, messages, temp, max_tokens):
    def go():
        sys_parts = [m["content"] for m in messages if m["role"] == "system"]
        contents = [{"role": "model" if m["role"] == "assistant" else "user",
                     "parts": [{"text": m["content"]}]}
                    for m in messages if m["role"] != "system"]
        gen = {"temperature": temp}
        if not c.get("no_max_tokens"):
            gen["maxOutputTokens"] = max_tokens
        body = {"contents": contents, "generationConfig": gen}
        if sys_parts:
            body["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(sys_parts)}]}
        url = (c["api_base"].rstrip("/") + "/models/" + c["model"]
               + ":generateContent")
        r = _post(url, json=body,
                  headers={"x-goog-api-key": c["api_key"]},
                  timeout=_timeout(c))
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    return go


def chat(messages, temperature=None, max_tokens=3500, retries=2):
    c = load()
    if not c.get("api_key") or not c.get("model"):
        raise RuntimeError("请先在【设置】里填写 API Key 和模型名")
    temp = c.get("temperature_write", 0.85) if temperature is None else temperature
    if c.get("protocol") == "gemini":
        send = _chat_gemini(c, messages, temp, max_tokens)
    else:
        send = _chat_openai(c, messages, temp, max_tokens)
    last = None
    for i in range(retries + 1):
        try:
            return send()
        except Exception as e:
            last = e
            if i < retries:
                time.sleep(2 + 2 * i)
    raise RuntimeError("模型调用失败：" + _friendly(last))


def list_models(api_base, api_key, protocol="openai"):
    """拉取可用模型列表。返回 (ok, msg, models)。"""
    base = (api_base or "").strip().rstrip("/")
    if not base:
        return False, "请先填写 API 地址", []
    try:
        if protocol == "gemini":
            r = _get(base + "/models?pageSize=200",
                     headers={"x-goog-api-key": api_key or ""},
                     timeout=20)
            r.raise_for_status()
            items = [m["name"].split("/")[-1]
                     for m in r.json().get("models", [])
                     if "generateContent"
                     in (m.get("supportedGenerationMethods") or [])]
        else:
            r = _get(base + "/models",
                     headers={"Authorization": "Bearer " + (api_key or "")},
                     timeout=20)
            r.raise_for_status()
            data = r.json().get("data") or r.json().get("models") or []
            items = [m.get("id") or m.get("name") for m in data
                     if m.get("id") or m.get("name")]
        items = sorted({i for i in items if i})
        if not items:
            return False, "接口没有返回模型列表，可直接手动填写模型名", []
        return True, f"获取到 {len(items)} 个模型", items
    except Exception as e:
        return False, _friendly(e) + "（不影响手动填写模型名）", []


def test_connection():
    c = load()
    if not c.get("api_key"):
        return False, "未填写 API Key"
    if not c.get("model"):
        return False, "未填写模型名"
    try:
        txt = chat([{"role": "user", "content": "请只回复两个字母：OK"}],
                   temperature=0.1, max_tokens=10, retries=0)
        return True, f"连接正常，模型返回：{txt.strip()[:20]}"
    except Exception as e:
        return False, str(e)


def extract_json(text):
    t = (text or "").strip()
    t = re.sub(r"```(?:json)?", "", t).strip()
    # 整段就是 JSON 时直接解析，保住顶层形状（对象/数组不混）
    try:
        return json.loads(t)
    except Exception:
        pass
    best, last = None, "返回内容里找不到 JSON 片段"
    for op, cl in (("{", "}"), ("[", "]")):
        i, j = t.find(op), t.rfind(cl)
        if i != -1 and j > i:
            raw = t[i:j + 1]
            try:
                data = json.loads(raw)
            except Exception as e:
                last = str(e)
                try:
                    data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
                except Exception:
                    data = None
            if data is not None and (best is None or i < best[0]):
                best = (i, data)
    if best:
        return best[1]
    raise ValueError("模型未返回有效JSON（" + last + "）：" + (text or "")[:120])


def ask_json(messages, log=print, want_list=False, item_key=None,
                need_keys=None, **kw):
    """chat + extract_json；解析失败把错误喂回给模型，自动重试一次。"""
    msgs = list(messages)
    last = None
    for attempt in (1, 2):
        raw = chat(msgs, **kw)
        try:
            data = extract_json(raw)
            if want_list:
                if not isinstance(data, list) or not data:
                    raise ValueError("返回的不是 JSON 数组")
                if item_key and not all(isinstance(x, dict) and item_key in x
                                        for x in data):
                    raise ValueError("数组元素缺少 " + item_key + " 字段")
            if need_keys:
                if not isinstance(data, dict):
                    raise ValueError("返回的不是 JSON 对象")
                miss = [k for k in need_keys if k not in data]
                if miss:
                    raise ValueError("返回的 JSON 缺少字段：" + "、".join(miss))
            return data
        except ValueError as e:
            last = e
            if attempt == 1:
                log("返回的 JSON 解析失败，把错误喂回去重试一次…")
                extra = ("你需要输出的是一个 JSON 数组（[...]，数组元素是选题对象）。"
                         if want_list else "")
                msgs = msgs + [
                    {"role": "assistant", "content": (raw or "")[:2000]},
                    {"role": "user", "content":
                        "你上面返回的内容无法按 JSON 解析（" + str(e)[:200] + "）。"
                        + extra +
                        "重新完整输出一遍：除 JSON 外不要输出任何文字；"
                        "字符串内部需要引用时一律用中文引号''「」《》，"
                        "不要出现未转义的英文双引号。"}]
    raise ValueError("重试一次仍失败——" + str(last))
