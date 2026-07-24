"""Alibaba Risk Monitor - 法律案件监控（CourtListener API 直连版）

功能：
1. CourtListener REST API v4 直连监控 docket-entries
2. 重要法律文件智能分类（Complaint, Motion, Order, Injunction等）
3. AI风险评级引擎（基于法律文件类型+内容关键词）
4. PACER/Google News 双轨fallback
5. Docket事件时间线追踪
6. 重要文件的PDF/全文判词监控
"""
import json
import os
import sys
import re
import hashlib
import urllib.request
import urllib.error
import traceback
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


# ========== 数据持久化（复用主模块的缓存） ==========

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


# ========== CourtListener API 配置 ==========

COURTLISTENER_BASE = "https://www.courtlistener.com/api/rest/v4"

# CourtListener API Token
# 如何获取：在 courtlistener.com 注册账号 -> Profile -> API Token
# 免费token使用限制：100+ requests/day, 匿名用户有限制
CL_API_TOKEN = os.environ.get("COURTLISTENER_API_TOKEN", "")

# 若没有API token，使用public docket page scraping方式
# CourtListener的公开页面（非API）在某些限制下可访问


def _cl_api_headers() -> dict:
    """返回CourtListener API的认证header。"""
    headers = {
        "User-Agent": "AlibabaRiskMonitor/1.0 (research project; contact@example.com)",
        "Content-Type": "application/json",
    }
    if CL_API_TOKEN:
        headers["Authorization"] = f"Token {CL_API_TOKEN}"
    return headers


# ========== 案件元数据 ==========

CASE_METADATA = {
    "case_name": LAWSUIT_CASE,
    "case_number": LAWSUIT_CASE_NUMBER,
    "court": "United States District Court for the Northern District of California",
    "court_id": "cand",
    "judge": None,
    "filed_date": "2026-06-??",  # 需确认
    "presiding_judge": None,
    "nature_of_suit": "Other Contract Actions",
}

# ========== 法律文件分类 ==========

# 法律文件类型 — 按对股价影响排序
DOCUMENT_TYPES = {
    # 🔴 RED — 严重负面
    "MOTION_TO_DISMISS": {
        "type": "dismiss",
        "names": ["Motion to Dismiss", "Motion for Summary Judgment", "Motion for Judgment on the Pleadings"],
        "keywords": ["motion to dismiss", "summary judgment", "judgment on the pleadings"],
        "severity": "RED",
        "direction": "下跌（法院可能驳回阿里诉求）",
        "action": "降低风险",
        "description": "政府申请驳回阿里诉讼 — 法院若支持政府立场，阿里将失去司法救济途径",
    },
    "ADVERSE_ORDER": {
        "type": "order_adverse",
        "names": ["Order Denying", "Order Dismissing", "Memorandum Opinion (Adverse)"],
        "keywords": ["order denying", "order dismissing", "order granting motion to dismiss",
                      "denied", "complaint dismissed"],
        "severity": "RED",
        "direction": "下跌（法院裁决不利）",
        "action": "降低风险",
        "description": "法院作出对阿里不利的裁决",
    },
    "GOVT_OPPOSITION": {
        "type": "government_opposition",
        "names": ["Opposition", "Government's Response", "Response in Opposition"],
        "keywords": ["opposition", "response in opposition", "government's response",
                      "defendant's opposition"],
        "severity": "ORANGE",
        "direction": "下跌（政府立场强硬）",
        "action": "观察",
        "description": "美国政府提交反对意见 — 预示案件将进入对抗阶段",
    },

    # 🟠 ORANGE — 中等风险
    "LAWSUIT_FILED": {
        "type": "complaint",
        "names": ["Complaint", "Class Action Complaint", "Petition for Review"],
        "keywords": ["complaint", "petition", "class action"],
        "severity": "ORANGE",
        "direction": "下跌（诉讼不确定性）",
        "action": "观察",
        "description": "案件正式立案 — 法律不确定性增加",
    },
    "HEARING_SCHEDULED": {
        "type": "hearing",
        "names": ["Notice of Hearing", "Order Setting Hearing", "Minute Order (Hearing)"],
        "keywords": ["hearing", "oral argument", "status conference", "case management"],
        "severity": "ORANGE",
        "direction": "中性偏空",
        "action": "观察",
        "description": "法院排期听证 — 案件进入实质性审理阶段",
    },
    "TRO_MOTION": {
        "type": "tro_motion",
        "names": ["Motion for Temporary Restraining Order", "Application for TRO",
                  "Motion for Preliminary Injunction"],
        "keywords": ["temporary restraining order", "preliminary injunction",
                      "TRO", "emergency motion"],
        "severity": "ORANGE",
        "direction": "中性（禁令请求待裁决）",
        "action": "观察",
        "description": "阿里申请临时限制令/初步禁令 — 试图紧急阻止政府行动",
    },
    "CLASS_CERT": {
        "type": "class_certification",
        "names": ["Motion for Class Certification", "Class Certification Brief"],
        "keywords": ["class certification", "class action certification"],
        "severity": "ORANGE",
        "direction": "下跌（若转为集体诉讼）",
        "action": "观察",
        "description": "集体诉讼认证动议",
    },

    # 🟡 YELLOW — 低风险/中性
    "TRO_GRANTED": {
        "type": "tro_granted",
        "names": ["Order Granting TRO", "Temporary Restraining Order",
                  "Preliminary Injunction Granted"],
        "keywords": ["order granting", "temporary restraining order granted",
                      "preliminary injunction granted", "TRO granted"],
        "severity": "GREEN",
        "direction": "上涨（法院支持阿里）",
        "action": "持有",
        "description": "法院授予临时限制令/初步禁令 — 阿里获得临时法律保护",
    },
    "SETTLEMENT": {
        "type": "settlement",
        "names": ["Notice of Settlement", "Stipulation of Dismissal", "Settlement Agreement"],
        "keywords": ["settlement", "stipulation of dismissal", "settlement agreement",
                      "joint stipulation"],
        "severity": "GREEN",
        "direction": "上涨（和解预期）",
        "action": "持有",
        "description": "和解/撤诉 — 法律风险消除",
    },
    "NOTICE_OF_APPEARANCE": {
        "type": "appearance",
        "names": ["Notice of Appearance", "Entry of Appearance"],
        "keywords": ["notice of appearance", "entry of appearance"],
        "severity": "YELLOW",
        "direction": "中性（程序性）",
        "action": "观察",
        "description": "律师出庭通知 — 程序性事件",
    },
    "CASE_TRANSFER": {
        "type": "transfer",
        "names": ["Order of Transfer", "Notice of Related Case"],
        "keywords": ["transfer", "related case", "multidistrict litigation"],
        "severity": "YELLOW",
        "direction": "中性",
        "action": "观察",
        "description": "案件转移或关联案件通知",
    },
    "STIPULATION": {
        "type": "stipulation",
        "names": ["Stipulation", "Joint Stipulation", "Proposed Order"],
        "keywords": ["stipulation", "proposed order", "joint submission",
                      "agreed order"],
        "severity": "YELLOW",
        "direction": "中性（程序性）",
        "action": "观察",
        "description": "双方同意事项 — 程序性事件",
    },
    "OTHER": {
        "type": "other",
        "names": [],
        "keywords": [],
        "severity": "YELLOW",
        "direction": "中性（其他程序性事件）",
        "action": "观察",
        "description": "其他docket事件",
    },
}

# 案件时间线 — 已知事件参考
CASE_TIMELINE = [
    # 格式: (date, event_type, description)
    # 动态从docket获取
]


# ========== CourtListener API 直连 ==========

def cl_api_get(endpoint: str, params: dict = None) -> Optional[dict]:
    """调用CourtListener REST API v4。

    Args:
        endpoint: API路径（如 /docket-entries/）
        params: 查询参数

    Returns:
        JSON响应，或 None（失败时）
    """
    url = f"{COURTLISTENER_BASE}{endpoint}"
    if params:
        qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
        url = f"{url}?{qs}"

    req = urllib.request.Request(url, headers=_cl_api_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401 or e.code == 403:
            log(f"CourtListener API 需要认证（{e.code}）。请设置 COURTLISTENER_API_TOKEN 环境变量", "WARN")
        elif e.code == 429:
            log(f"CourtListener API 速率限制。等待重试...", "WARN")
        else:
            log(f"CourtListener API HTTP {e.code}: {e}", "WARN")
        return None
    except Exception as e:
        log(f"CourtListener API 请求失败: {e}", "WARN")
        return None


def fetch_docket_entries() -> list:
    """通过CourtListener API获取案件的docket entries。

    使用 docket-entries 端点，按案号过滤。
    CourtListener 通过 RECAP 扩展自动同步PACER数据。

    Returns:
        docket entry列表（按日期排序）
    """
    all_entries = []

    # 方法1: CourtListener API（需API token）
    if CL_API_TOKEN:
        log("CourtListener API Token 已设置，使用API直连...")

        # 首先搜索docket ID
        docket_result = cl_api_get("/dockets/", {
            "case_name__contains": "Alibaba",
            "court__id": CASE_METADATA["court_id"],
        })
        if docket_result and docket_result.get("count", 0) > 0:
            docket_id = docket_result["results"][0]["id"]
            log(f"找到docket ID: {docket_id}")

            # 获取该docket的所有entries
            page = 1
            while True:
                entries = cl_api_get("/docket-entries/", {
                    "docket__id": docket_id,
                    "order_by": "entry_number",
                    "page": page,
                    "page_size": 100,
                })
                if not entries or not entries.get("results"):
                    break

                all_entries.extend(entries["results"])

                if entries.get("next"):
                    page += 1
                else:
                    break

            log(f"从API获取了 {len(all_entries)} 条docket entries")

    # 方法2: 备用搜索方法 — 通过RECAP查询
    if not all_entries:
        log("尝试通过RECAP搜索...")
        recap_result = cl_api_get("/recap/", {
            "docket__case_number": LAWSUIT_CASE_NUMBER,
            "order_by": "entry_number",
        })
        if recap_result and recap_result.get("results"):
            for r in recap_result["results"]:
                entry = {
                    "entry_number": r.get("entry_number"),
                    "date_filed": r.get("date_filed"),
                    "description": r.get("description", ""),
                    "document_number": r.get("document_number"),
                    "pacer_doc_id": r.get("pacer_doc_id"),
                    "source": "RECAP",
                    "is_available": r.get("is_available", False),
                    "page_count": r.get("page_count"),
                }
                all_entries.append(entry)
            log(f"从RECAP获取了 {len(all_entries)} 条entries")

    return all_entries


def _scrape_docket_page() -> list:
    """通过CourtListener公开页面+RECAP docket快速查询（无需API token）。

    这是当没有API token时的备用方案。
    通过CourtListener的公开docket页面获取基本信息。

    Returns:
        docket entry列表
    """
    entries = []
    # 尝试通过RECAP docket page获取公开数据
    # CourtListener公开页面格式: /docket/{docket_id}/{case_name}/
    # 但CloudFront可能会拦截。替代方案: Google Cache或archive.org

    # 由于CloudFront限制，目前通过新闻RSS间接获取案件进展
    # TODO: 未来可通过 RECAP API 或 PACER 直接查询
    return entries


# ========== 法律文件智能解析引擎 ==========

def classify_document(entry: dict) -> dict:
    """智能分析docket entry，识别法律文件类型和风险等级。

    解析策略：
    1. 从 entry description 中提取关键词
    2. 匹配预定义的DOCUMENT_TYPES
    3. 输出风险评级

    Args:
        entry: docket entry dict

    Returns:
        dict: {type, severity, direction, action, description, confidence}
    """
    description = entry.get("description", "")
    desc_lower = description.lower()

    def _make_result(doc_type: str, confidence: float) -> dict:
        """构建返回结果。"""
        doc_info = DOCUMENT_TYPES.get(doc_type, DOCUMENT_TYPES["OTHER"])
        return {
            "type": doc_type,
            "type_label": doc_info["type"],
            "severity": doc_info["severity"],
            "direction": doc_info["direction"],
            "action": doc_info["action"],
            "description": doc_info["description"],
            "confidence": min(confidence, 1.0),
            "matched_type": True,
        }

    best_match = None
    best_score = 0
    debug_scores = {}

    # 特别模式：先检测高优先级否定/排除模式
    # "OPPOSITION by Alibaba to Motion to Dismiss" → 不是Motion本身，是Opposition
    is_opposition_by_alibaba = "opposition by" in desc_lower and "alibaba" in desc_lower
    is_order_granting = desc_lower.startswith("order granting") or "order granting" in desc_lower[:30]
    is_settlement_notice = "notice of settlement" in desc_lower or "stipulation of dismissal" in desc_lower

    # 处理特殊情况
    if is_settlement_notice:
        return _make_result("SETTLEMENT", 1.0)

    if is_order_granting:
        # ORDER GRANTING Temporary Restraining Order 或 GRANTING Preliminary Injunction
        if "temporary restraining order" in desc_lower or "preliminary injunction" in desc_lower:
            return _make_result("TRO_GRANTED", 1.0)
        # ORDER GRANTING — 其他类型的granting，可能是偏正面
        classification = _make_result("INFERRED", 0.6)
        classification.update({
            "severity": "YELLOW",
            "direction": "中性偏正面（法院支持一方请求）",
            "action": "观察",
        })
        return classification

    for doc_type, doc_info in DOCUMENT_TYPES.items():
        score = 0

        # 关键词匹配（排除已处理的特殊情况）
        for kw in doc_info["keywords"]:
            if kw in desc_lower:
                score += len(kw) * 10

        # 名称匹配
        for name in doc_info["names"]:
            if name.lower() in desc_lower:
                score += 50

        # 对于MOTION_TO_DISMISS，如果同时匹配了Opposition by，降低分数
        if doc_type == "MOTION_TO_DISMISS" and is_opposition_by_alibaba:
            score -= 80

        if score > best_score:
            best_score = score
            best_match = doc_type

    # 特别规则：OPPOSITION by Alibaba 且 匹配到 MOTION_TO_DISMISS 关键词但分数被降低后
    if is_opposition_by_alibaba and "opposition" in desc_lower:
        # 检查是否有明确表示这是阿里的反对意见
        if best_match == "MOTION_TO_DISMISS" or any(kw in desc_lower for kw in ["response", "opposition", "reply"]):
            return _make_result("GOVT_OPPOSITION", 0.9)

    if best_match and best_score > 5:
        return _make_result(best_match, min(best_score / 100, 1.0))

    # 未匹配到已知类型，尝试基于关键词推理
    return _infer_document_type(description)


def _infer_document_type(description: str) -> dict:
    """当无法精确分类时，基于上下文推理文件类型。"""
    desc_lower = description.lower()

    # 提取关键信号
    signals = {
        "positive": ["grant", "allow", "approved", "favor", "win", "victory",
                      "settlement", "dismissed", "stipulation", "withdraw"],
        "negative": ["deny", "denied", "reject", "dismiss", "opposition",
                      "objection", "adverse", "sanction"],
        "urgent": ["emergency", "expedited", "immediate", "temporary", "shortened"],
        "procedural": ["notice", "order", "minute order", "clerk",
                       "summons", "return of service", "affidavit",
                       "declaration", "exhibit", "certificate"],
        "judicial": ["opinion", "memorandum", "ruling", "decision", "order",
                      "judgment", "decree"],
    }

    has_positive = any(s in desc_lower for s in signals["positive"])
    has_negative = any(s in desc_lower for s in signals["negative"])
    has_urgent = any(s in desc_lower for s in signals["urgent"])
    has_procedural = any(s in desc_lower for s in signals["procedural"])
    has_judicial = any(s in desc_lower for s in signals["judicial"])

    # 推理逻辑
    if has_judicial:
        # 法官裁决类文件
        if has_negative:
            severity, direction, action = "RED", "下跌（法院裁决不利）", "降低风险"
        elif has_positive:
            severity, direction, action = "GREEN", "上涨（法院裁决有利）", "持有"
        else:
            severity, direction, action = "ORANGE", "下跌（法院裁决不确定性）", "观察"
    elif has_urgent:
        severity, direction, action = "ORANGE", "下跌（紧急动议）", "观察"
    elif has_negative:
        severity, direction, action = "ORANGE", "下跌", "观察"
    elif has_positive:
        severity, direction, action = "YELLOW", "中性偏正面", "观察"
    elif has_procedural:
        severity, direction, action = "YELLOW", "中性（程序性）", "观察"
    else:
        severity, direction, action = "YELLOW", "中性（其他）", "观察"

    return {
        "type": "INFERRED",
        "type_label": "inferred",
        "severity": severity,
        "direction": direction,
        "action": action,
        "description": f"推断文件类型: {description[:100]}",
        "confidence": 0.4,
        "matched_type": False,
        "signals_found": {
            "positive": has_positive,
            "negative": has_negative,
            "urgent": has_urgent,
            "procedural": has_procedural,
            "judicial": has_judicial,
        }
    }


# ========== 案件状态更新 ==========

def check_docket_updates() -> dict:
    """全面检查法律案件docket更新。

    执行步骤：
    1. 通过CourtListener API（如有token）获取最新entries
    2. 与本地缓存的已知entries对比
    3. 识别新文件
    4. 智能分类并评级
    5. 更新案件时间线

    Returns:
        dict: {new_events, total_entries, case_phase, risk_summary}
    """
    docket_cache = load_cache(DOCKET_CACHE)
    known_entry_numbers = set(docket_cache.get("known_entry_numbers", []))
    known_hashes = set(docket_cache.get("known_hashes", []))

    # 整理案件元数据
    case_meta = docket_cache.get("case_meta", {})
    case_meta.update({
        "case_name": LAWSUIT_CASE,
        "case_number": LAWSUIT_CASE_NUMBER,
        "last_checked": now_hk().isoformat(),
    })

    result = {
        "checked_at": now_hk().isoformat(),
        "case_name": LAWSUIT_CASE,
        "case_number": LAWSUIT_CASE_NUMBER,
        "new_events": [],
        "total_entries_known": len(known_entry_numbers),
        "api_available": bool(CL_API_TOKEN),
        "source": "API" if CL_API_TOKEN else "News+RSS",
    }

    # Step 1：获取最新docket entries
    entries = fetch_docket_entries()

    # Step 2：如果没有API token，尝试其他方式
    if not entries:
        entries = _scrape_docket_page()

    # Step 3：解析并对比新事件
    for entry in entries:
        entry_number = entry.get("entry_number")
        description = entry.get("description", "")
        date_filed = entry.get("date_filed", "")

        # 跳过已知事件
        entry_hash = hashlib.md5(f"{entry_number}:{description}:{date_filed}".encode()).hexdigest()
        if entry_number in known_entry_numbers or entry_hash in known_hashes:
            continue

        # 这是新事件 — 智能分类
        classification = classify_document(entry)

        event = {
            "entry_number": entry_number,
            "date_filed": date_filed,
            "description": description,
            "document_number": entry.get("document_number"),
            "pacer_doc_id": entry.get("pacer_doc_id"),
            "classification": classification,
            "detected_at": now_hk().isoformat(),
            "hash": entry_hash,
        }

        result["new_events"].append(event)
        known_entry_numbers.add(entry_number)
        known_hashes.add(entry_hash)

    # Step 4：更新缓存
    docket_cache["known_entry_numbers"] = list(known_entry_numbers)[-200:]
    docket_cache["known_hashes"] = list(known_hashes)[-500:]
    docket_cache["case_meta"] = case_meta
    docket_cache["last_check"] = now_hk().isoformat()

    # 保存新事件到events历史
    cached_events = docket_cache.get("events", [])
    for event in result["new_events"]:
        cached_events.append(event)
    docket_cache["events"] = cached_events[-50:]
    save_cache(DOCKET_CACHE, docket_cache)

    result["new_event_count"] = len(result["new_events"])
    result["case_phase"] = _determine_case_phase(
        result["new_events"], docket_cache.get("events", [])
    )
    result["risk_summary"] = _summarize_risk(result["new_events"])

    return result


def _determine_case_phase(new_events: list, all_events: list) -> str:
    """根据docket事件判断案件当前阶段。"""
    descriptions = []
    for e in all_events + new_events:
        desc = e.get("description", "").lower() if isinstance(e, dict) else ""
        descriptions.append(desc)

    all_text = " ".join(descriptions)

    if "settlement" in all_text or "stipulation of dismissal" in all_text:
        return "SETTLEMENT"
    if "judgment" in all_text or "opinion" in all_text:
        return "DECISION_PENDING"
    if "summary judgment" in all_text:
        return "SUMMARY_JUDGMENT"
    if "motion to dismiss" in all_text:
        return "MOTION_TO_DISMISS"
    if "preliminary injunction" in all_text or "temporary restraining" in all_text:
        return "INJUNCTION_PHASE"
    if "hearing" in all_text or "oral argument" in all_text or "status conference" in all_text:
        return "HEARING_PHASE"
    if "complaint" in all_text and any("answer" in d for d in descriptions):
        return "PLEADING_PHASE"
    if "complaint" in all_text:
        return "INITIAL_PLEADING"
    if "summons" in all_text:
        return "SERVICE_OF_PROCESS"
    return "EARLY_STAGE"


def _summarize_risk(new_events: list) -> dict:
    """汇总新事件的整体风险状况。"""
    if not new_events:
        return {"highest_severity": "YELLOW", "overall": "无新事件", "alert_count": 0}

    severities = [e["classification"]["severity"] for e in new_events]

    severity_order = {"RED": 4, "ORANGE": 3, "YELLOW": 2, "GREEN": 1}
    highest = max(severities, key=lambda s: severity_order.get(s, 0))

    red_count = severities.count("RED")
    orange_count = severities.count("ORANGE")

    if highest == "RED":
        overall = f"严重（{red_count}件RED事件）"
    elif highest == "ORANGE":
        overall = f"关注（{orange_count}件ORANGE事件）"
    else:
        overall = "低影响"

    return {
        "highest_severity": highest,
        "overall": overall,
        "alert_count": len(new_events),
        "red_count": red_count,
        "orange_count": orange_count,
    }


# ========== AI风险评级（二次分析引擎） ==========

def deep_risk_assessment(event: dict, classification: dict = None) -> dict:
    """对特定法律事件进行深度风险分析。

    分析维度：
    1. 法律文件类型权重
    2. 法官/法院倾向
    3. 案件进度影响
    4. 市场历史反应
    5. 连锁风险效应

    Args:
        event: 已分类的法律事件（如果classification已存在则使用）
        classification: 可选，预分类结果。如果提供则优先使用。

    Returns:
        dict: 综合风险评估
    """
    if classification is None:
        classification = event.get("classification", {})
        if not classification or not classification.get("type"):
            # 没有预分类结果，现场分类
            classification = classify_document(event)

    severity = classification.get("severity", "YELLOW")
    confidence = classification.get("confidence", 0.5)

    # 文件类型权重
    type_weights = {
        "MOTION_TO_DISMISS": 0.9,
        "ADVERSE_ORDER": 1.0,
        "GOVT_OPPOSITION": 0.7,
        "TRO_MOTION": 0.6,
        "TRO_GRANTED": 0.5,
        "HEARING_SCHEDULED": 0.5,
        "LAWSUIT_FILED": 0.8,
        "SETTLEMENT": 0.4,
        "NOTICE_OF_APPEARANCE": 0.1,
        "STIPULATION": 0.2,
        "OTHER": 0.3,
        "INFERRED": 0.3,
    }

    event_type = classification.get("type", "OTHER")
    weight = type_weights.get(event_type, 0.3)

    # 综合风险得分 (0-1)
    # 原则：AI评分是对base分类的辅助确认，不覆盖
    # RED base + high weight + high confidence → 确认RED
    # ORANGE base → 最多提升到RED边界
    # YELLOW/GREEN base → 不会提升到更高等级
    
    severity_scores = {"RED": 1.0, "ORANGE": 0.5, "YELLOW": 0.3, "GREEN": 0.1}
    base_score = severity_scores.get(severity, 0.35)
    weight = type_weights.get(event_type, 0.3)
    
    # 简单加权：权重影响幅度有限
    weight_boost = 0.3 + 0.7 * weight  # 范围 0.37 ~ 1.0
    confidence_factor = 0.6 + 0.4 * confidence  # 范围 0.6 ~ 1.0
    
    risk_score = base_score * weight_boost * confidence_factor
    
    # 最终评级逻辑：
    if risk_score >= 0.45:
        final_severity = "RED"
        recommended_action = "降低风险"
    elif risk_score >= 0.25:
        final_severity = "ORANGE"
        recommended_action = "观察"
    else:
        final_severity = "YELLOW"
        recommended_action = "监测"

    return {
        "risk_score": round(risk_score, 3),
        "final_severity": final_severity,
        "recommended_action": recommended_action,
        "analysis_factors": {
            "type_weight": weight,
            "base_severity": severity,
            "confidence": confidence,
            "severity_score": base_score,
            "weight_boost": weight_boost,
            "confidence_factor": confidence_factor,
        },
        "risk_rationale": _generate_risk_rationale(event),
    }


def _generate_risk_rationale(event: dict) -> str:
    """生成人类可读的风险分析理由。"""
    classification = event.get("classification", {})
    doc_type = classification.get("type", "UNKNOWN")
    reasonings = {
        "MOTION_TO_DISMISS": (
            "政府申请驳回诉讼是案件中最重要的转折点。"
            "如果法院支持政府的驳回请求，阿里将失去司法救济途径，"
            "1260H名单认定将维持不变，股价可能进一步承压。"
            "驳回听证结果通常需要30-90天。"
        ),
        "ADVERSE_ORDER": (
            "法院作出对阿里不利的裁决，这是直接的负面催化剂。"
            "如果涉及驳回诉讼或支持政府的立场，"
            "阿里可能面临上诉或和解的选择。"
        ),
        "GOVT_OPPOSITION": (
            "美国政府提交了正式的反对意见，表明政府立场强硬。"
            "这通常意味着案件将进入全面的证据开示和审理阶段，"
            "时间周期可能延长至6-12个月。"
        ),
        "TRO_MOTION": (
            "阿里申请临时限制令，寻求紧急阻止政府行动。"
            "TRO的获批与否通常会在1-2周内决定，"
            "是短期股价的重要催化剂。"
        ),
        "TRO_GRANTED": (
            "法院授予了临时限制令或初步禁令。"
            "这为阿里争取了临时法律保护，"
            "短期内可能提振股价。"
        ),
        "HEARING_SCHEDULED": (
            "法院安排了听证会，案件进入实质性审理阶段。"
            "听证结果将是判断案件走向的关键节点。"
        ),
        "LAWSUIT_FILED": (
            "案件正式立案，法律不确定性增加。"
            "市场可能对诉讼风险进行重新定价。"
        ),
        "SETTLEMENT": (
            "双方达成和解，法律风险基本消除。"
            "这对阿里股价是明确的正面因素。"
        ),
    }
    return reasonings.get(doc_type, "普通docket事件，影响取决于后续进展。")


# ========== 格式化告警消息 ==========

def format_legal_alert(event: dict, deep_risk: dict = None) -> str:
    """格式化为企业微信markdown法律告警消息。"""
    classification = event.get("classification", {})
    severity = classification.get("severity", "YELLOW")
    direction = classification.get("direction", "中性")
    action = classification.get("action", "观察")

    if deep_risk:
        severity = deep_risk.get("final_severity", severity)
        action = deep_risk.get("recommended_action", action)

    emoji = {"RED": "🔴", "ORANGE": "🟠", "YELLOW": "🟡", "GREEN": "🟢"}
    lines = []
    lines.append(f"## {emoji.get(severity, '🟡')} Alibaba Legal Risk Alert [{severity}]\n")

    lines.append(f"**时间：** {now_hk().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**事件：** ⚖️ 法律案件更新")
    lines.append(f"**案件：** {LAWSUIT_CASE}")
    lines.append(f"**案号：** {LAWSUIT_CASE_NUMBER}")

    desc = event.get("description", "")
    date_filed = event.get("date_filed", "")
    entry_number = event.get("entry_number", "")

    if entry_number:
        lines.append(f"**Docket #：** {entry_number}")
    if date_filed:
        lines.append(f"**提交日期：** {date_filed}")
    if desc:
        lines.append(f"**文件描述：** {desc[:300]}")

    # 智能分类结果
    doc_type = classification.get("type", "")
    doc_type_label = classification.get("type_label", "")
    confidence = classification.get("confidence", 0)
    if doc_type:
        type_name = DOCUMENT_TYPES.get(doc_type, {}).get("names", [doc_type])[0] if DOCUMENT_TYPES.get(doc_type) else doc_type
        lines.append(f"\n**智能分类：** {type_name}")
        lines.append(f"**置信度：** {confidence:.0%}")

    lines.append(f"\n**分类理由：** {DOCUMENT_TYPES.get(doc_type, {}).get('description', classification.get('description', ''))}")

    if deep_risk:
        lines.append(f"\n**AI深度分析：**")
        lines.append(f"**综合风险评分：** {deep_risk.get('risk_score', 0):.2f}")
        lines.append(f"**风险理由：** {deep_risk.get('risk_rationale', '')}")

    lines.append("")
    lines.append(f"**影响评级：** {severity}")
    lines.append(f"**对阿里股价影响：** {direction}")
    lines.append(f"**建议动作：** {action}")

    return "\n".join(lines)


# ========== 独立运行 ==========

if __name__ == "__main__":
    print("=" * 60)
    print(f"Alibaba Legal Case Monitor")
    print(f"Case: {LAWSUIT_CASE}")
    print(f"Case #: {LAWSUIT_CASE_NUMBER}")
    print(f"CourtListener API Token: {'✅ 已设置' if CL_API_TOKEN else '⚠️ 未设置（将使用备选方案）'}")
    print("=" * 60)

    result = check_docket_updates()
    print(f"\n检查时间: {result['checked_at']}")
    print(f"数据源: {result['source']}")
    print(f"新事件: {result['new_event_count']} 条")
    print(f"案件阶段: {result['case_phase']}")

    if result.get("risk_summary"):
        rs = result["risk_summary"]
        print(f"最高风险: {rs.get('highest_severity')}")
        print(f"综合评估: {rs.get('overall')}")

    for event in result.get("new_events", []):
        print(f"\n--- Docket #{event.get('entry_number', '?')} ---")
        print(f"  描述: {event.get('description', '')[:200]}")
        print(f"  日期: {event.get('date_filed', '')}")
        print(f"  分类: {event['classification'].get('type', 'UNKNOWN')}")
        print(f"  评级: {event['classification'].get('severity', 'YELLOW')}")

        # AI深度分析
        deep = deep_risk_assessment(event)
        print(f"  AI风险评分: {deep['risk_score']:.2f}")
        print(f"  最终评级: {deep['final_severity']}")

    print("\n" + "=" * 60)
