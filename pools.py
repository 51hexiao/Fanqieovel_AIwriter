# -*- coding: utf-8 -*-
"""选题元素池。五个维度词表与番茄发布页官方分类一字不差（经平台审核、
决定流量分发），从用户发布页分类面板提取；再叠加手艺维度：
无脑爽文线（内部键"悬疑"）=底牌×打脸对象；细腻写实线（内部键"温情"）
=内核×设定×意象。

内部键沿用旧名是为了数据库兼容，展示一律走 LINE_NAMES。
平台分类有增补时，在 exe 同目录放 categories.json 即可覆盖对应维度，
例如：{"主分类": ["婚姻家庭", "悬疑惊悚"]}。
"""
import json
import random
import re

import paths

# 内部键 → 展示名（数据库里的 line 字段沿用内部键）
LINE_NAMES = {"悬疑": "无脑爽文", "温情": "细腻写实"}

# ---- 番茄发布页官方分类（2026-10 从 publish-short 分类面板提取）----
CAT = {
    "主分类": [
        "婚姻家庭", "女生生活", "男生生活", "现言甜宠", "虐心婚恋",
        "青春虐恋", "男生情感", "女性成长", "悬疑惊悚", "玄幻仙侠",
        "宫斗宅斗", "男频衍生", "女频衍生", "年代", "纯爱", "其他",
        "古言甜宠", "古风世情", "都市日常", "男频脑洞", "女频脑洞",
        "民国旧影", "古言虐恋", "历史古代",
    ],
    "情节": [
        "追妻火葬场", "追夫火葬场", "真假千金", "先婚后爱", "打脸逆袭",
        "破镜重圆", "系统", "金手指", "大女主", "女性互助", "穿越", "重生",
        "暗恋", "婚恋", "权谋", "架空", "养崽文", "团宠", "无限流",
        "末日求生", "游戏动漫", "规则怪谈", "民间奇闻", "影视", "科幻",
        "推理", "直播", "升级流", "外卖", "鉴宝", "黑道", "都市江湖",
        "都市异能", "仕途",
    ],
    "角色": [
        "白月光", "霸总", "婆媳", "青梅竹马", "姐弟恋", "凤凰男",
        "校花校草", "女配", "医生", "替身", "病娇", "赘婿", "校霸",
        "影帝影后", "萌宝", "糙汉", "万人迷", "女总裁", "奶爸", "神医",
        "特种兵", "首富", "魔法", "吸血鬼", "欧美帮派", "狼人",
    ],
    "情绪": [
        "先虐后甜", "甜宠", "虐文", "爽文", "救赎", "惊悚", "励志",
        "沙雕搞笑",
    ],
    "背景": [
        "家庭", "职场", "校园", "娱乐圈", "现代", "古代", "豪门世家",
        "西幻魔法", "西方古典", "西方现代",
    ],
}


def _load_cat_override():
    f = paths.DATA_DIR / "categories.json"
    if not f.exists():
        return
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        for k, v in (data or {}).items():
            if k in CAT and isinstance(v, list) and v:
                CAT[k] = [str(x).strip() for x in v if str(x).strip()]
    except Exception:
        pass



_CAT_BASE = {k: list(v) for k, v in CAT.items()}
_load_cat_override()

_CAT_DIMS = ("主分类", "情节", "角色", "情绪", "背景")


def extract_tokens(raw):
    """从粘贴的 HTML/文本里按顺序提取中文词（2-8 字）。"""
    txt = re.sub(r"(?is)<(script|style)[\s\S]*?</\1>", " ", raw)
    txt = re.sub(r"<[^>]+>", "\n", txt)
    txt = re.sub(r"&[a-zA-Z#0-9]+;", "\n", txt)
    out = []
    for tok in re.split(r"[\s、，,;；/|.·\[\]（）「」『』《》\"'：:]+", txt):
        tok = tok.strip()
        if re.fullmatch(r"[\u4e00-\u9fff]{2,8}", tok):
            out.append(tok)
    return out


def parse_categories_raw(raw):
    """粘贴内容按顺序解析：遇到维度名（主分类/情节/角色/情绪/背景）即切换
    当前维度，其后词语归入该维度；维度名出现之前的词进 unknown。"""
    dims, unknown, cur = {}, [], None
    for w in extract_tokens(raw):
        if w in _CAT_DIMS:
            cur = w
            dims.setdefault(cur, [])
        elif cur:
            if w not in dims[cur]:
                dims[cur].append(w)
        elif w not in unknown:
            unknown.append(w)
    return dims, unknown


def overridden_dims():
    f = paths.DATA_DIR / "categories.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8")) or {}
        return [k for k, v in data.items()
                if k in CAT and isinstance(v, list) and v]
    except Exception:
        return []


def apply_cat_override(dims):
    """保存解析结果：对应维度整表替换并落盘（与覆盖语义一致）。"""
    changed = {}
    for dim, words in (dims or {}).items():
        if dim not in CAT or not isinstance(words, list):
            continue
        words = [str(w).strip() for w in words if str(w).strip()]
        if words and words != CAT[dim]:
            changed[dim] = len(words)
            CAT[dim] = words
    if changed:
        f = paths.DATA_DIR / "categories.json"
        data = {}
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8")) or {}
            except Exception:
                data = {}
        for dim in changed:
            data[dim] = list(CAT[dim])
        f.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    return changed


def reset_cat_override():
    f = paths.DATA_DIR / "categories.json"
    if f.exists():
        f.unlink()
    CAT.clear()
    CAT.update({k: list(v) for k, v in _CAT_BASE.items()})


# ---- 各线子集（带权；重复合表示抽中概率更高）----
SUS_MAIN = (["女频脑洞"] * 3 + ["婚姻家庭"] * 2 + ["都市日常"] * 2
            + ["现言甜宠"] * 2 + ["男频脑洞"] * 2 + [
                "女性成长", "虐心婚恋", "女生生活", "男生生活",
                "青春虐恋", "年代"])
WARM_MAIN = (["婚姻家庭"] * 3 + [
    "女生生活", "男生情感", "女性成长", "都市日常", "年代", "纯爱",
    "现言甜宠", "古风世情", "青春虐恋", "民国旧影"])
SUS_PLOT = (["打脸逆袭"] * 3 + ["系统"] * 2 + ["金手指"] * 2
            + ["升级流"] * 2 + ["真假千金"] * 2 + ["重生"] * 2 + [
                "鉴宝", "直播", "大女主", "先婚后爱", "追妻火葬场",
                "追夫火葬场", "都市异能", "规则怪谈", "无限流",
                "末日求生", "权谋", "穿越"])
WARM_PLOT = [
    "破镜重圆", "先婚后爱", "暗恋", "婚恋", "女性互助", "养崽文",
    "团宠", "真假千金", "重生", "穿越", "追妻火葬场", "追夫火葬场",
    "大女主",
]
SUS_EMO = ["爽文"] * 5 + ["先虐后甜"] * 2 + ["沙雕搞笑"]
WARM_EMO = (["甜宠"] * 2 + ["先虐后甜"] * 2 + ["救赎"] * 2
            + ["励志", "虐文"])


def _w(rng, pool, dim):
    """从本线子集抽签；子集里出现平台已下架的词时回落到全量官方词表。"""
    pool = [t for t in pool if t in CAT[dim]] or CAT[dim]
    return rng.choice(pool)


# ---- 手艺维度（官方分类管流量入口，这些管内容差异化）----
# 爽文线：人设=主角姿态（清醒/淡人流，憋屈让读者受），底牌=逆袭引擎
STANCE = [
    "清醒得吓人，早把所有人看透", "无欲无求，随时可以转身离开",
    "不吵不闹，安静收拾行李准备走", "对错付的真心说断就断",
    "不解释不挽留，笑着看他们表演", "后路早就铺好，心里一点不慌",
    "只把自己的日子当回事", "看破不说破，等他们自己露馅",
    "谁劝都没用，心意已决", "从不主动出手，但谁也别想拿捏",
    "对烂人烂事不多看一眼", "冷眼旁观，等一个收网的时机",
    "要钱有钱要退路有退路，就等他们先翻脸",
    "捧着最真的心，也留着最狠的后手",
]
ENGINE = [
    "重生回到关键的那一天", "能听见身边人的真心话", "突然继承一笔巨款",
    "绑定了一个打脸系统", "能预知三分钟后的麻烦", "马甲是全网顶流",
    "隐藏身份是首富独女", "隐藏身份是隐世神医", "退役的传奇兵王",
    "握着反派的致命把柄", "我是仇人找了很多年的恩人",
    "手里的旧物是稀世珍宝", "全网粉丝都在等我回归",
    "病弱的外表下藏着顶尖本事", "一个电话能调动全城人脉的贵人",
    "高考被顶替的真相就攥在我手里", "存款和退路早已备好",
]

W_CORE = [
    "来不及说出口的道歉", "迟到的理解", "隐瞒了一辈子的守护",
    "没送出去的礼物", "没赶上的告别", "三十年的误会",
    "替对方活成他想要的样子", "被岁月美化的故人", "说不出口的谢谢",
    "一笔还不清的亏欠", "错过的重逢", "最后一程的陪伴",
]

# 现实 → 轻梦幻连续谱；穿越/重来只是其中一格
W_SET = [
    "完全现实", "一封迟到多年的信", "反复出现的同一个梦",
    "梦里的叮嘱应验了", "旧照片里多出一个人影", "重回过去的一天",
    "与年轻时的故人重逢", "故人离世那天时间停住",
    "临终愿望换来的重逢", "遗物里发现另一个身份",
]

W_OBJ = [
    "一台老缝纫机", "一沓寄不出去的信", "厨房那盏灯", "半盒没织完的毛线",
    "一把备用钥匙", "一部老式座机", "阳台上的月季", "一本翻旧的挂历",
    "一双纳好的鞋垫", "一辆二八自行车", "抽屉里的药盒", "一口腌菜坛子",
    "一件洗白的外套", "收音机里的整点报时",
]


def sample_combo(rng: random.Random):
    """无脑爽文线（内部键"悬疑"）：官方分类（主分类×情节×背景×情绪）
    × 人设 × 底牌。人设=清醒/淡人流姿态，憋屈让读者受、主角不内耗。"""
    return {
        "main": _w(rng, SUS_MAIN, "主分类"),
        "plot": _w(rng, SUS_PLOT, "情节"),
        "bg": rng.choice(CAT["背景"]),
        "emo": _w(rng, SUS_EMO, "情绪"),
        "stance": rng.choice(STANCE),
        "engine": rng.choice(ENGINE),
    }


def sample_warm_combo(rng: random.Random):
    """细腻写实线（内部键"温情"）：官方分类（主分类×情节×情绪）
    × 内核 × 设定 × 意象。"""
    return {
        "main": _w(rng, WARM_MAIN, "主分类"),
        "plot": _w(rng, WARM_PLOT, "情节"),
        "emo": _w(rng, WARM_EMO, "情绪"),
        "core": rng.choice(W_CORE),
        "set": rng.choice(W_SET),
        "obj": rng.choice(W_OBJ),
    }
