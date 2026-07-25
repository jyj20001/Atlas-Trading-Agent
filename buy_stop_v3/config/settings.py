"""
Buy Stop V3 — 配置管理
"""

import os
from pathlib import Path

# ── 项目路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
OUTPUT_DIR = PROJECT_ROOT / "output"

# 自动创建目录
for d in [DATA_DIR, LOGS_DIR, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── 巨潮资讯 API 配置 ──
CNINFO = {
    # 巨潮资讯公告/报表API端点
    "BASE_URL": "http://www.cninfo.com.cn/new",
    "DISCLOSURE_URL": "http://www.cninfo.com.cn/new/disclosure",
    # 业绩预告查询
    "PERFORMANCE_FORECAST_URL": "http://www.cninfo.com.cn/new/hisAnnouncement/query",
    # 财务报表查询
    "FINANCIAL_URL": "http://www.cninfo.com.cn/new/financial/financial/queryHisBulletin",
    # 请求间隔(秒)，避免被封
    "REQUEST_INTERVAL": 1.0,
    "MAX_RETRIES": 3,
    "TIMEOUT": 30,
    # User-Agent 池
    "USER_AGENTS": [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ],
}

# ── 东方财富 API 配置（备用） ──
EASTMONEY = {
    "KLINE_URL": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
    "QUOTE_URL": "https://push2.eastmoney.com/api/qt/stock/get",
    "TIMEOUT": 15,
}

# ── Buy Stop 策略参数 ──
BUY_STOP = {
    # 长期趋势
    "MA200_CHECK": True,
    # 突破条件：成交量 >= 均量 * VOLUME_RATIO
    "VOLUME_RATIO": 1.5,
    # 20日均量周期
    "VOLUME_MA_PERIOD": 20,
    # 整理周期（检测箱体用）
    "CONSOLIDATION_LOOKBACK": 60,
    # 突破窗口（突破20日高后几天内有效）
    "BREAKOUT_WINDOW_DAYS": 5,
    # 连续涨停过滤
    "MAX_CONSECUTIVE_LIMIT": 3,
    # 5日涨幅过滤
    "MAX_5D_CHANGE_PCT": 30,
    "EXCLUDE_50D_CHANGE": True,
    # 换手率 —— 按市值分类
    "TURNOVER": {
        "large_cap": {"min": 1.5, "max": 5.0, "threshold": 500e8},   # >500亿
        "mid_cap": {"min": 3.0, "max": 10.0, "threshold": 100e8},    # 100-500亿
        "small_cap": {"min": 5.0, "max": 15.0, "threshold": 0},      # <100亿
    },
}

# ── 系统信息（仅展示，不影响策略/评分/参数） ──
OBSERVATION = {
    "VERSION": "v3.5 Stable",
    "START_DATE": "2026-07-24",       # Production Observation Phase 开始日期
    "DURATION": 30,                     # 观察期总天数（交易日）
    "LABEL": "Production Observation Phase",
}

# ── 日志 ──
LOG = {
    "LEVEL": "INFO",
    "FILE": LOGS_DIR / "buy_stop.log",
    "FORMAT": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
}
