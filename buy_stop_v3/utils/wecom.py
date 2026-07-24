"""
Buy Stop V3 — 企业微信推送模块

预留接口，当前为空实现。
激活方式：设置 WECOM_WEBHOOK_URL 环境变量或写入 config.yaml。

使用方法（未来）：
  from utils.wecom import push_markdown
  push_markdown("# Buy Stop 扫描报告\\n...")
"""

import json
import os
from typing import Optional

from utils.logger import logger

# 从环境变量读取，不硬编码
_WEBHOOK_URL = os.environ.get("WECOM_WEBHOOK_URL", "")


def push_text(content: str, mentioned_list: Optional[list] = None) -> bool:
    """推送文本消息（预留）"""
    if not _WEBHOOK_URL:
        logger.debug("企业微信未配置，跳过推送")
        return False
    # TODO: 实现推送
    logger.info(f"企业微信推送: {content[:50]}...")
    return True


def push_markdown(content: str) -> bool:
    """推送Markdown消息（预留）"""
    if not _WEBHOOK_URL:
        return False
    # TODO: 实现推送
    return True


def push_scan_report(summary) -> bool:
    """推送扫描报告（预留）"""
    if not _WEBHOOK_URL:
        return False
    candidates = summary.candidates
    lines = [f"## Buy Stop 扫描报告"]
    lines.append(f"扫描: {summary.total}只 | 候选: {len(candidates)}")
    if candidates:
        for i, r in enumerate(candidates[:5], 1):
            s = r.stock
            o = r.output
            lines.append(f"{i}. **{s.name}({s.code})** "
                         f"评分{o.combined_score} {o.recommendation}")
    push_markdown("\n".join(lines))
    return True
