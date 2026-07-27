"""Alibaba Risk Monitor - 主监控脚本

功能：
1. 法律案件监控 (Docket更新、法院命令等)
2. 政策新闻监控 (关键词过滤，只报告高影响事件)
3. 价格/成交量异常监控
4. 企业微信推送告警

运行方式：由cron定时调用，每个tick执行一次检查。
"""
import json
import os
import sys
import time
import hashlib
import urllib.request
import urllib.error
import traceback
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

try:
    from config import *
except ImportError:
    print("FATAL: Cannot load config.py. Make sure it's in the same directory.")
    sys.exit(1)

HK_TZ = timezone(timedelta(hours=8))


def now_hk():
    return datetime.now(HK_TZ)


def log(msg: str, level="INFO"):
    ts = now_hk().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


# ===== 数据持久化 =====

def ensure_dirs():
    os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "output"), exist_ok=True)


def get_cache_path(name: str) -> str:
    return os.path.join(DATA_DIR, name)


def load_cache(name: str) -> dict:
    path = get_cache_path(name)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            log(f"Cache load error ({name}): {e}", "WARN")
            return {}
    return {}


def save_cache(name: str, data: dict):
    path = get_cache_path(name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_history(event: dict):
    history_path = os.path.join(DATA_DIR, LOG_FILE)
    events = []
    if os.path.exists(history_path):
        try:
            with open(history_path, "r") as f:
                events = json.load(f)
        except Exception:
            events = []
    events.append(event)
    if len(events) > 100:
        events = events[-100:]
    with open(history_path, "w") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)


# ===== 企业微信推送 =====

def send_wechat(text: str) -> bool:
    if not WECHAT_WEBHOOK_URL:
        log("WeChat webhook not configured, skip push", "WARN")
        return False

    payload = {
        "msgtype": "markdown",
        "markdown": {"content": text}
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        WECHAT_WEBHOOK_URL, data=data,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            if result.get("errcode") == 0:
                log("WeChat push success", "INFO")
                return True
            else:
                log(f"WeChat push error: {result}", "ERROR")
                return False
    except Exception as e:
        log(f"WeChat push failed: {e}", "ERROR")
        return False


# ===== 事件分类与评级逻辑 =====

# 高影响关键词 — 这些词出现在新闻标题中时认定为高影响事件
HIGH_IMPACT_KW = {
    # 法律/制裁类 (RED)
    "sanction": "RED",
    "制裁": "RED",
    "delist": "RED",
    "退市": "RED",
    "ban": "RED",
    "禁止": "RED",
    "restrict": "RED",
    "限制": "RED",
    "blacklist": "RED",
    "黑名单": "RED",
    "investigation": "ORANGE",
    "调查": "ORANGE",
    "probe": "ORANGE",
    "scrutiny": "ORANGE",
    "审查": "ORANGE",
    "criminal": "RED",
    "刑事": "RED",
    "lawsuit": "ORANGE",
    "诉讼": "ORANGE",

    # 案件进展类 (取决于内容)
    "injunction": None,  # 需要根据上下文判断
    "injunctive relief": None,
    "preliminary injunction": None,
    "temporary restraining order": None,
    "hearing": None,
    "oral argument": None,
    "motion to dismiss": None,
    "motion for summary judgment": None,
    "judge order": None,
    "court ruling": None,
    "trial": None,

    # 流动性/退市风险 (RED)
    "withdraw": "RED",
    "移除上市地位": "RED",
    "NDAA": "RED",
    "National Defense Authorization Act": "RED",

    # 国防部/Pentagon更新
    "1260H": "ORANGE",
    "Chinese military company": "ORANGE",
    "中国军工企业": "ORANGE",
    "CMC list": "ORANGE",
    "China Military Companies": "ORANGE",
    "defense contract": "ORANGE",
    "国防合同": "ORANGE",
    "Pentagon removes": "YELLOW",  # 移除可能是好消息
    "remove.*military": None,

    # AI相关特别风险
    "AI distillation": "ORANGE",
    "Claude Code": "ORANGE",
    "Anthropic": "ORANGE",
    "export control": "ORANGE",
    "出口管制": "ORANGE",
    "chip ban": "ORANGE",
    "芯片禁令": "ORANGE",
}

# 低影响关键词 — 这些词出现在标题中时，即使匹配了Alibaba也跳过
LOW_IMPACT_KW = [
    "analyst rating", "analyst report", "upgrade", "downgrade",
    "target price", "price target", "牛熊证", "warrant",
    "options", "option chain", "put", "call",
    "dividend", "分红",
    "technical analysis", "chart pattern",
    "PT raised", "PT lowered",
    "etf", "ETF",
    "insider trading", "insider transaction",
    "share buyback", "回购",
    "short interest", "做空比例",
    "fund flow", "资金流向",
    "portfolio", "持仓",
    "stock position", "shares purchased", "shares sold",
    "rating maintained",
    "market cap",
    "52-week",
    "moving average",
    "RSI", "MACD",
    "valuation",
    "PE ratio",
]

# 必须严格匹配的高影响标题模式 — 这些事件100%推送
HIGH_IMPACT_TITLE_PATTERNS = [
    r"Alibaba.*sue(s)?.*Pentagon",
    r"Alibaba.*sue(s)?.*Defense",
    r"Alibaba.*sue(s)?.*U\.S\.",
    r"Alibaba.*lawsuit",
    r"Alibaba.*blacklist",
    r"Alibaba.*delist",
    r"Alibaba.*1260H",
    r"Alibaba.*Chinese Military",
    r"Alibaba.*military company",
    r"Pentagon.*Alibaba",
    r"Pentagon.*blacklist",
    r"Defense Department.*Alibaba",
    r"Alibaba.*ban.*Claude",
    r"Alibaba.*Claude Code",
    r"AI distillation",
    r"Alibaba.*export control",
    r"Alibaba.*sanction",
    r"Alibaba.*NDAA",
    r"Trump.*Alibaba",
    r"Alibaba.*Trump",
    r"Alibaba.*trade war",
    r"CFIUS.*Alibaba",
    r"Alibaba.*CFIUS",
    r"Alibaba.*injunction",
    r"court.*Alibaba.*ruling",
    r"judge.*Alibaba",
    r"Alibaba.*military.*list",
    r"Alibaba.*Defense.*contract",
    r"European Union.*Alibaba.*fine",
    r"EU.*Alibaba.*fine",
    r"Alibaba.*(€|EUR|euro).*(fine|penalty)",
    r"Alibaba.*fine.*(€|EUR|euro)",
]

# 仅登记非普通新闻的普通Alibaba新闻，如果属于低影响类别则跳过
NEWS_QUALIFYING_PATTERNS = [
    r"Alibaba.*Pentagon",
    r"Pentagon.*Alibaba",
    r"1260H",
    r"military company",
    r"military.*list",
    r"defense.*department",
    r"Department of Defense",
    r"blacklist",
    r"delist",
    r"sue(s)?",
    r"lawsuit",
    r"injunction",
    r"Anthropic",
    r"AI distillation",
    r"Claude Code",
    r"sanction",
    r"NDAA",
    r"export control",
    r"chip ban",
    r"CFIUS",
    r"trade war",
    r"court",
    r"judge.*ruling",
]


def classify_news_impact(title: str, summary: str) -> Optional[dict]:
    """分类新闻影响等级。

    Returns:
        dict with {severity, direction, action} if it's a qualifying event,
        None if it's noise/normal news that should be skipped.
    """
    combined = (title + " " + summary).lower()

    # 1. 检查是否匹配高影响标题模式
    for pattern in HIGH_IMPACT_TITLE_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            severity, direction, action = _judge_severity_by_context(combined)
            return {"severity": severity, "direction": direction, "action": action,
                    "matched_rule": f"高影响标题模式: {pattern}"}

    # 2. 检查低影响关键词 — 如果是低影响新闻直接跳过
    for kw in LOW_IMPACT_KW:
        if kw.lower() in combined:
            return None  # 跳过低影响新闻

    # 3. 检查是否至少匹配一个限定关键词
    qualifies = False
    for pattern in NEWS_QUALIFYING_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            qualifies = True
            break

    if not qualifies:
        return None  # 不相关的普通新闻

    # 4. 从HIGH_IMPACT_KW判断评级
    severity, direction, action = _judge_severity_by_context(combined)
    return {"severity": severity, "direction": direction, "action": action,
            "matched_rule": "关键词匹配"}


def _judge_severity_by_context(combined_text: str) -> tuple:
    """根据上下文判断严重级别。"""
    text = combined_text.lower()

    # 正面信号
    positive_signals = [
        "remove", "removal", "removed", "delist", "delisted", "strike down",
        "overturn", "victory", "win", "reprieve", "exemption", "temporary",
        "relief", "approve", "approval", "settlement",
        "移除", "胜诉", "豁免", "临时", "批准",
    ]
    negative_signals = [
        "ban", "blacklist", "sanction", "restrict", "restriction",
        "criminal", "investigation", "probe", "scrutiny",
        "lawsuit", "sue", "suing", "fine", "penalty",
        "delisting", "withdraw",
        "禁止", "制裁", "限制", "调查", "审查", "诉讼", "罚款", "退市",
    ]

    has_positive = any(sig in text for sig in positive_signals)
    has_negative = any(sig in text for sig in negative_signals)

    # 特殊组合判断
    # "sue" + "pentagon" = 起诉，短期负面，中长期待定
    if "sue" in text and ("pentagon" in text or "defense" in text or "military" in text):
        # 起诉本身是负面（不确定性），但如果提到"win"或"reprieve"则偏正面
        if "reprieve" in text or "temporary" in text or "relief" in text:
            return "ORANGE", "下跌（短期）", "观察"
        return "ORANGE", "下跌（不确定性）", "观察"

    # fine / penalty
    if "fine" in text or "penalty" in text or "罚款" in text:
        amount_match = re.search(r'(\d+\.?\d*)\s*(million|billion|M|B|亿|亿?欧元|亿?美元|€|\$)?', text)
        amount = amount_match.group(0) if amount_match else "未知"
        if "€" in text or "euro" in text or "欧元" in text:
            return "ORANGE", f"下跌（欧盟罚款{amount}）", "观察"
        return "ORANGE", f"下跌（罚款{amount}）", "观察"

    # Blacklist / 1260H
    if "blacklist" in text or "1260h" in text or "military company" in text:
        if has_positive:
            return "YELLOW", "中性偏正面", "观察"
        if has_negative:
            return "ORANGE", "下跌", "观察"
        return "YELLOW", "中性（待确认影响）", "观察"

    # 出口管制 / chip ban
    if "export control" in text or "chip ban" in text or "出口管制" in text:
        return "ORANGE", "下跌", "观察"

    # delisting
    if "delist" in text or "退市" in text or "withdraw" in text:
        return "RED", "下跌（严重）", "降低风险"

    # NDAA
    if "ndaa" in text or "National Defense Authorization" in text:
        return "RED", "下跌（严重）", "降低风险"

    # AI相关
    if "anthropic" in text or "claude code" in text or "ai distillation" in text:
        if "ban" in text or "禁止" in text:
            return "ORANGE", "下跌", "观察"
        return "YELLOW", "中性", "观察"

    # Anthropic / AI distillation 风险
    if "distillation" in text:
        return "ORANGE", "中性偏空", "观察"

    # Trump / CFIUS
    if "trump" in text or "cfius" in text:
        return "ORANGE", "下跌", "观察"

    # 法院命令/禁令 (需结合上下文)
    if "injunction" in text or "temporary restraining order" in text:
        return "YELLOW", "中性", "观察"
    if "hearing" in text or "oral argument" in text:
        return "YELLOW", "中性", "观察"
    if "dismiss" in text:
        if "denied" in text:
            return "RED", "下跌", "降低风险"
        return "YELLOW", "中性偏空", "观察"

    # 默认判断
    if has_negative:
        return "ORANGE", "下跌", "观察"
    if has_positive:
        return "YELLOW", "上涨", "持有"

    return "YELLOW", "中性", "观察"


# ===== 法律案件监控（CourtListener API 直连版） =====

try:
    from legal_monitor import (
        check_docket_updates, deep_risk_assessment, format_legal_alert,
        CL_API_TOKEN as HAS_API_TOKEN,
        DOCUMENT_TYPES,
    )
    LEGAL_MONITOR_AVAILABLE = True
except ImportError as e:
    log(f"Legal monitor module not available: {e}", "WARN")
    LEGAL_MONITOR_AVAILABLE = False
    HAS_API_TOKEN = ""


def check_court_docket() -> Optional[dict]:
    """检查法院docket更新。

    使用升级后的 legal_monitor 模块：
    - CourtListener API v4 直连（有token时）
    - 智能法律文件分类与风险评级
    - AI深度风险分析
    """
    if not LEGAL_MONITOR_AVAILABLE:
        log("Legal monitor (legal_monitor.py) not available", "WARN")
        return {
            "checked_at": now_hk().isoformat(),
            "new_events": [],
            "new_event_count": 0,
            "case_number": LAWSUIT_CASE_NUMBER,
            "case_name": LAWSUIT_CASE,
            "api_available": False,
            "source": "unavailable",
        }

    # 调用升级后的docket检查
    result = check_docket_updates()

    # 从新闻RSS中补充案件相关新闻（作为docket信息的交叉验证）
    # 新闻中检测到的案件进展会作为 additional_events 返回
    result["source"] = "API" if HAS_API_TOKEN else "RSS+News"

    return result


# ===== 新闻监控（精确过滤版） =====

def check_news() -> dict:
    """检查新闻RSS，只报告高影响事件。"""
    news_cache = load_cache(NEWS_CACHE)
    seen_urls = set(news_cache.get("seen_urls", []))

    result = {
        "checked_at": now_hk().isoformat(),
        "total_sources_attempted": 0,
        "total_sources_success": 0,
        "new_articles": [],
        "filtered_out": 0,
    }

    for feed_url in NEWS_FEEDS:
        result["total_sources_attempted"] += 1
        try:
            articles = _parse_rss_feed(feed_url)
            if articles is None:
                continue
            result["total_sources_success"] += 1

            for article in articles:
                url = article.get("url", "")
                title = article.get("title", "")
                summary = article.get("summary", "")

                if url and url not in seen_urls:
                    seen_urls.add(url)

                    # 先检查关键词匹配
                    combined_text = (title + " " + summary).lower()
                    matched_keywords = []
                    for kw in NEWS_KEYWORDS:
                        if kw.lower() in combined_text:
                            matched_keywords.append(kw)

                    if not matched_keywords:
                        continue  # 不相关，跳过

                    # 分类影响等级
                    impact = classify_news_impact(title, summary)
                    if impact is None:
                        # 低影响新闻，跳过
                        result["filtered_out"] += 1
                        continue

                    article["matched_keywords"] = matched_keywords
                    article["impact"] = impact
                    article["found_at"] = now_hk().isoformat()
                    result["new_articles"].append(article)

        except Exception as e:
            log(f"Failed to fetch feed {feed_url}: {e}", "WARN")
            continue

    # 更新seen_urls缓存
    seen_urls_list = list(seen_urls)
    if len(seen_urls_list) > 1000:
        seen_urls_list = seen_urls_list[-1000:]
    news_cache["seen_urls"] = seen_urls_list
    news_cache["last_check"] = now_hk().isoformat()
    save_cache(NEWS_CACHE, news_cache)

    result["new_count"] = len(result["new_articles"])
    return result


def _parse_rss_feed(feed_url: str) -> Optional[list]:
    """解析RSS Feed。"""
    import xml.etree.ElementTree as ET
    import feedparser

    try:
        feed = feedparser.parse(feed_url)
        if not feed.entries:
            return None

        articles = []
        for entry in feed.entries:
            article = {
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "summary": entry.get("summary", "")[:500],
                "published": entry.get("published", ""),
                "source": feed_url,
                "source_name": _extract_source_name(feed_url),
            }
            articles.append(article)
        return articles
    except Exception as e:
        log(f"RSS parse error for {feed_url}: {e}", "WARN")
        return None


def _extract_source_name(feed_url: str) -> str:
    if "news.google.com" in feed_url:
        return "Google News"
    if "finance.yahoo.com" in feed_url:
        return "Yahoo Finance"
    if "reuters.com" in feed_url:
        return "Reuters"
    return feed_url


# ===== 构建告警消息 =====

def format_alert_message(alert_type: str, data: dict, impact: dict) -> str:
    """格式化为企业微信markdown消息。"""
    lines = []
    severity = impact.get("severity", "YELLOW")
    direction = impact.get("direction", "中性")
    action = impact.get("action", "观察")

    # 标题带等级emoji
    emoji = {"RED": "🔴", "ORANGE": "🟠", "YELLOW": "🟡", "GREEN": "🟢"}
    lines.append(f"## {emoji.get(severity, '🟡')} Alibaba Risk Alert [{severity}]\n")

    lines.append(f"**时间：** {now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

    if alert_type == "price":
        lines.append(f"**事件：** 📊 价格异常波动")
        lines.append(f"**股票：** {data.get('symbol', '')}")
        lines.append(f"**当前价：** {data.get('last_price', '')}")
        lines.append(f"**涨跌幅：** **{data.get('change_pct', '')}%**")
        lines.append(f"**来源：** Futubull / TradingView")

    elif alert_type == "volume":
        lines.append(f"**事件：** 📈 成交量异常")
        lines.append(f"**股票：** {data.get('symbol', '')}")
        lines.append(f"**今日量：** {data.get('volume', '')}")
        lines.append(f"**20日均量：** {data.get('avg_volume', '')}")
        lines.append(f"**量比：** **{data.get('volume_ratio', '')}x**")
        lines.append(f"**来源：** TradingView")

    elif alert_type == "legal":
        # 使用升级后的法律告警格式（含智能分类+AI深度分析）
        if LEGAL_MONITOR_AVAILABLE and 'deep_analysis' in data:
            message = format_legal_alert(data, data.get('deep_analysis'))
            return message

        # 向后兼容的格式
        lines.append(f"**事件：** ⚖️ 法律案件更新")
        lines.append(f"**案件：** {data.get('case_name', LAWSUIT_CASE)}")
        lines.append(f"**案号：** {data.get('case_number', LAWSUIT_CASE_NUMBER)}")

        # 升级后的分类信息
        classification = data.get('classification', {})
        if classification.get('type'):
            lines.append(f"**文件类型：** {DOCUMENT_TYPES.get(classification['type'], {}).get('names', [classification.get('type')])[0] if DOCUMENT_TYPES.get(classification['type']) else classification['type']}")
            lines.append(f"**置信度：** {classification.get('confidence', 0):.0%}")

        lines.append(f"**详情：** {data.get('description', '')[:300]}")
        lines.append(f"**来源：** {data.get('source', 'Court Docket')}")

    elif alert_type == "policy":
        lines.append(f"**事件：** 📰 政策/风险新闻")
        lines.append(f"**标题：** **{data.get('title', '')}**")
        summary = data.get('summary', '')
        # 清理HTML标签
        summary_clean = re.sub(r'<[^>]+>', '', summary)[:200]
        if summary_clean:
            lines.append(f"**摘要：** {summary_clean}")
        lines.append(f"**来源：** {data.get('source_name', data.get('source', 'News Feed'))}")
        if data.get('matched_keywords'):
            lines.append(f"**匹配：** {', '.join(data['matched_keywords'])}")
        matched_rule = impact.get("matched_rule", "")
        if matched_rule:
            lines.append(f"**规则：** {matched_rule}")

    lines.append("")
    lines.append(f"**影响评级：** {severity}")
    lines.append(f"**对阿里股价影响：** {direction}")
    lines.append(f"**建议动作：** {action}")

    return "\n".join(lines)


# ===== 主循环 =====

def run_once():
    """单次执行检查。"""
    ensure_dirs()
    log("=" * 60)
    log("Alibaba Risk Monitor - 开始扫描")

    alerts = []
    errors = []

    # === 1. 法律案件检查（升级版：CourtListener API + 智能分类 + AI深度分析） ===
    try:
        log("检查法律案件docket...")
        api_status = "API直连" if HAS_API_TOKEN else "RSS+新闻间接监控"
        log(f"数据源: {api_status}")
        docket_result = check_court_docket()
        if docket_result and docket_result.get("new_event_count", 0) > 0:
            log(f"法律案件: 发现 {docket_result['new_event_count']} 条新docket更新!", "ALERT")
            for event in docket_result["new_events"]:
                classification = event.get("classification", {})
                severity = classification.get("severity", "ORANGE")
                direction = classification.get("direction", "下跌")
                action = classification.get("action", "观察")

                # AI深度分析
                deep_analysis = deep_risk_assessment(event) if LEGAL_MONITOR_AVAILABLE else None
                if deep_analysis:
                    severity = deep_analysis.get("final_severity", severity)
                    action = deep_analysis.get("recommended_action", action)

                impact = {
                    "severity": severity,
                    "direction": direction,
                    "action": action,
                }
                alert_data = dict(event)
                if deep_analysis:
                    alert_data["deep_analysis"] = deep_analysis

                alerts.append({
                    "type": "legal",
                    "data": alert_data,
                    "impact": impact,
                })
                entry_num = event.get("entry_number", "?")
                desc = event.get("description", "")[:80]
                log(f"⚖️ Docket #{entry_num}: {desc} [{severity}]", "ALERT")
        elif docket_result:
            total = docket_result.get('total_entries_known', docket_result.get('cached_events_before', 0))
            phase = docket_result.get('case_phase', 'UNKNOWN')
            log(f"法律案件: 无新事件 (已跟踪 {total} 条docket | 案件阶段: {phase})")
        else:
            log("法律案件: 无法访问docket")
    except Exception as e:
        errors.append(f"法律案件检查失败: {e}")
        log(traceback.format_exc(), "ERROR")

    # === 2. 新闻扫描 ===
    try:
        log("检查新闻...")
        news_result = check_news()
        log(f"新闻: {news_result.get('new_count', 0)} 条新相关 ({news_result.get('filtered_out', 0)} 条低影响已过滤) | 检查了 {news_result.get('total_sources_success', 0)}/{news_result.get('total_sources_attempted', 0)} 个源")

        if news_result.get("new_count", 0) > 0:
            for article in news_result["new_articles"]:
                impact = article.get("impact", {"severity": "YELLOW", "direction": "中性", "action": "观察"})
                alerts.append({
                    "type": "policy",
                    "data": article,
                    "impact": impact,
                })
                log(f"新相关新闻: {article.get('title', '')[:80]} [{impact['severity']}]")

    except Exception as e:
        errors.append(f"新闻扫描失败: {e}")
        log(traceback.format_exc(), "ERROR")

    # === 输出 & 推送 ===
    if alerts:
        log(f"\n=== {len(alerts)} 条告警 ===")

        # 如果只有YELLOW级别告警，合并为一条不推送摘要
        has_red_orange = any(a["impact"]["severity"] in ("RED", "ORANGE") for a in alerts)

        for alert in alerts:
            message = format_alert_message(
                alert["type"], alert["data"], alert["impact"]
            )
            log(f"\n{message}\n", "ALERT")

            # RED/ORANGE推送企业微信
            severity = alert["impact"]["severity"]
            if severity in ("RED", "ORANGE"):
                push_ok = send_wechat(message)
                if push_ok:
                    log(f"企业微信推送成功 ({severity})")
                else:
                    log(f"企业微信推送失败", "WARN")
            else:
                log(f"{severity}告警，不推送企业微信（仅记录）")

            append_history(alert)

        # 如果没有RED/ORANGE但有多条YELLOW，推送一条摘要
        if not has_red_orange and len(alerts) > 3:
            summary_msg = (
                f"## 🟡 Alibaba Risk Monitor 摘要\n\n"
                f"**时间：** {now_hk().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"**发现 {len(alerts)} 条YELLOW级别事件**\n"
                f"**均为低影响，已记录日志，无需立即操作。**\n"
            )
            for i, a in enumerate(alerts[:5], 1):
                title = a["data"].get("title", a["data"].get("description", "未知"))[:60]
                summary_msg += f"\n{i}. {title} [{a['impact']['severity']}]"
            if len(alerts) > 5:
                summary_msg += f"\n\n...以及 {len(alerts) - 5} 条更多"
            send_wechat(summary_msg)
            log("推送YELLOW摘要到企业微信")

        # 保存告警
        output_path = os.path.join(DATA_DIR, "output", f"alerts_{now_hk().strftime('%Y%m%d_%H%M%S')}.json")
        with open(output_path, "w") as f:
            json.dump(alerts, f, ensure_ascii=False, indent=2)
        log(f"告警已保存到 {output_path}")
    else:
        log("无告警")

    if errors:
        log(f"\n错误汇总:")
        for e in errors:
            log(f"  - {e}", "ERROR")

    log("Alibaba Risk Monitor - 扫描完成")
    log("=" * 60)

    return {
        "alerts_count": len(alerts),
        "alert_severities": [a["impact"]["severity"] for a in alerts],
        "errors": errors,
    }


if __name__ == "__main__":
    run_once()
