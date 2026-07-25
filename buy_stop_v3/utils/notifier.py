"""
Buy Stop V3 — 企业微信通知模块

使用企业微信机器人 Webhook 推送扫描结果。
推送规则：
  - A+ 级 (>=105)：推送详情
  - A 级 (>=95)：推送详情
  - B+ 及以下：不推送
  - 无候选：推送"今日无符合条件"

配置方式：
  export WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"

未配置时：静默跳过，只写DEBUG日志。
"""

import json
import os
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from config.settings import OBSERVATION
from utils.logger import logger

# ── 配置 ──

_WEBHOOK_URL = os.environ.get("WECOM_WEBHOOK_URL", "").strip()

# 推送阈值
_PUSH_SCORE_MIN = 95  # 只推送 A 级及以上
_A_PLUS_MIN = 105     # A+ 阈值


def _get_observation_day() -> int:
    """计算当前观察期第几天（仅统计交易日，排除周末）。

    从 OBSERVATION.START_DATE 开始算第 1 天，不超过 DURATION。
    仅用于展示，不影响任何策略/评分/参数。
    """
    try:
        start = datetime.strptime(OBSERVATION["START_DATE"], "%Y-%m-%d").date()
    except (ValueError, KeyError):
        return 0
    today = date.today()
    if today < start:
        return 0

    day_count = 0
    current = start
    while current <= today:
        if current.weekday() < 5:  # 周一到周五
            day_count += 1
        current += timedelta(days=1)

    return min(day_count, OBSERVATION.get("DURATION", 30))


def _observation_header() -> str:
    """生成 Observation 展示信息头部（纯展示，不影响任何逻辑）"""
    day = _get_observation_day()
    version = OBSERVATION.get("VERSION", "?")
    return (
        f"Atlas Trading Agent\n"
        f"Version: {version}\n"
        f"Observation: Day {day} / {OBSERVATION.get('DURATION', 30)}\n"
    )


def is_configured() -> bool:
    """检查企业微信Webhook是否已配置"""
    return bool(_WEBHOOK_URL)


def _send_markdown(markdown_text: str) -> bool:
    """
    发送 Markdown 消息到企业微信机器人

    参数:
        markdown_text: Markdown 格式消息内容

    返回:
        bool — 是否发送成功
    """
    if not _WEBHOOK_URL:
        logger.debug("企业微信未配置 (WECOM_WEBHOOK_URL)，跳过推送")
        return False

    payload = json.dumps({
        "msgtype": "markdown",
        "markdown": {"content": markdown_text},
    }, ensure_ascii=False).encode("utf-8")

    try:
        req = Request(_WEBHOOK_URL, data=payload,
                      headers={"Content-Type": "application/json"},
                      method="POST")
        with urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            result = json.loads(body)
            if result.get("errcode") == 0:
                logger.info("企业微信推送成功")
                return True
            else:
                logger.warning(f"企业微信推送返回错误: {body}")
                return False
    except URLError as e:
        logger.warning(f"企业微信推送网络错误: {e}")
        return False
    except Exception as e:
        logger.warning(f"企业微信推送异常: {e}")
        return False


def _build_no_candidate_msg(summary) -> str:
    """构建无候选时的消息"""
    lines = []
    lines.append(f"📊 Buy Stop 每日扫描报告\n")
    lines.append(_observation_header())
    lines.append(f"**日期：**{date.today().isoformat()}")
    lines.append(f"**扫描数量：**{summary.total} 只")
    lines.append(f"**候选数量：**0")
    lines.append(f"")
    lines.append(f"今日无符合Buy Stop条件股票。")
    lines.append(f"当前市场环境下，策略未发现符合条件的突破机会。")
    return "\n".join(lines)


def _build_candidate_msg(summary) -> str:
    """构建有候选时的消息（仅A级及以上）"""
    lines = []
    lines.append(f"🔥 Buy Stop 每日扫描报告\n")
    lines.append(_observation_header())
    lines.append(f"**日期：**{date.today().isoformat()}")
    lines.append(f"**扫描数量：**{summary.total} 只")
    lines.append(f"**候选数量：**{len(summary.candidates)} 只")
    lines.append(f"")

    # 筛选 A 级及以上
    push_list = [r for r in summary.candidates
                 if r.combined_score >= _PUSH_SCORE_MIN]

    if not push_list:
        lines.append(f"今日无 A 级以上候选，暂停推送详情。")
        return "\n".join(lines)

    for rank, result in enumerate(push_list, 1):
        o = result.output
        s = o.signal if o else None
        stock = result.stock

        lines.append(f"**#{rank} {stock.name}({stock.code})**")
        lines.append(f"> 评分：**{o.combined_score}/130**")
        lines.append(f"> 评级：{'A+ 级' if o.combined_score >= _A_PLUS_MIN else 'A 级'}")
        lines.append(f"> 突破阶段：{o.breakout_stage}")
        lines.append(f"")

        if s:
            lines.append(f"> Buy Stop价格：**{s.breakout_price}**")
            lines.append(f"> 当前价格：{s.price}")
            lines.append(f"> 止损：{s.stop_loss}")
            lines.append(f"> 目标：{s.target}")
            lines.append(f"")

        # 入选原因
        reasons = []
        if s:
            reasons.append(f"✅ 技术评分 {s.total_score}/100")
        reasons.append(f"✅ 基本面 +{o.fundamental_score}")
        reasons.append(f"✅ 市场 {o.market_score}/5 ({o.market_status})")
        reasons.append(f"✅ 板块 +{o.sector_score}")
        lines.append(f"> **入选原因：**")
        for r_text in reasons:
            lines.append(f"> {r_text}")
        lines.append(f"")

        # 风险
        if o.risk_flags:
            lines.append(f"> ⚠️ **风险：**")
            for flag in o.risk_flags[:3]:
                lines.append(f"> - {flag}")
        lines.append(f"")

    return "\n".join(lines)


def notify_scan(summary) -> bool:
    """
    扫描完成后的通知入口。
    根据候选评分决定发送内容，未配置Webhook时静默跳过。

    参数:
        summary: ScanSummary 对象

    返回:
        bool — 是否成功发送（或True当未配置时）
    """
    if not _WEBHOOK_URL:
        logger.debug("企业微信未配置 (WECOM_WEBHOOK_URL)，跳过推送")
        return True

    if not summary.candidates:
        msg = _build_no_candidate_msg(summary)
        logger.info("推送：今日无Buy Stop候选")
        return _send_markdown(msg)

    # 检查是否有A级以上候选
    has_push = any(r.combined_score >= _PUSH_SCORE_MIN
                   for r in summary.candidates)
    if not has_push:
        logger.info("候选评分均低于A级，不推送详情")
        return True

    msg = _build_candidate_msg(summary)
    return _send_markdown(msg)
