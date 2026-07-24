"""Alibaba Risk Monitor - 配置（升级版）"""

# ===== 股票代码 =====
HK_STOCK = "HK.09988"
US_STOCK = "US.BABA"
TV_HK_SYMBOL = "HKEX_DLY:9988"
TV_US_SYMBOL = "NASDAQ:BABA"

# ===== 法律案件 =====
LAWSUIT_CASE = "Alibaba Group Holding Limited v. United States Department of Defense"
LAWSUIT_CASE_NUMBER = "5:26-cv-06227"
LAWSUIT_CHECK_INTERVAL_HOURS = 12

# CourtListener API Token
# 获取方式：https://www.courtlistener.com/ -> 注册 -> Profile -> API Token
# 免费token：100+ requests/day，足够本监控使用
# 也可以通过环境变量设置：export COURTLISTENER_API_TOKEN="your-token-here"
COURTLISTENER_API_TOKEN = ""  # 填入你的token，留空则使用RSS备选方案

# Court docket sources
DOCKET_SOURCES = [
    # CourtListener / RECAP
    "https://www.courtlistener.com/docket/5:26-cv-06227/alibaba-group-holding-limited-v-united-states-department-of-defense/",
    # PACER
    "https://pcl.uscourts.gov/pcl/pages/multiPartySearch.jsf",
    # Google Cache (fallback)
    "https://webcache.googleusercontent.com/search?q=cache:https://www.courtlistener.com/docket/5:26-cv-06227/",
]

# ===== 新闻监控关键词 =====
NEWS_KEYWORDS = [
    "Alibaba",
    "BABA",
    "9988",
    "Pentagon",
    "Department of Defense",
    "China Military Company",
    "1260H",
    "Anthropic",
    "AI distillation",
    "阿里巴巴",
    "国防部",
    "中国军工企业",
    "制裁",
    "delisting",
    "退市",
    "injunction",
    "preliminary injunction",
    "temporary restraining order",
    "court ruling",
    "judge order",
    "motion to dismiss",
    "summary judgment",
]

# ===== RSS/News Feeds =====
NEWS_FEEDS = [
    # Google News RSS
    "https://news.google.com/rss/search?q=Alibaba+OR+BABA+OR+9988&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Alibaba+1260H+OR+Department+of+Defense+OR+China+Military&hl=en-US&gl=US&ceid=US:en",
    # Reuters
    "https://www.reuters.com/arc/outboundfeeds/newsletter/?topic=alibaba-group-holding-limited&published=true",
    # Yahoo Finance
    "https://finance.yahoo.com/rss/headline?s=BABA",
    # Google News - Legal
    "https://news.google.com/rss/search?q=Alibaba+lawsuit+OR+injunction+OR+pentagon+OR+1260H&hl=en-US&gl=US&ceid=US:en",
]

# ===== 价格异常监控 =====
PRICE_CHANGE_THRESHOLD_PCT = 3.0  # 日涨跌超过此百分比触发
VOLUME_THRESHOLD_MULTIPLIER = 2.0  # 成交量超过20日均量此倍数触发
OHLCV_LOOKBACK_DAYS = 120  # 获取K线天数，用于计算20日均量

# ===== 企业微信推送 =====
WECHAT_WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=255672b4-4e5b-46f8-b8e1-9f639b68a09b"

# ===== 数据存储 =====
DATA_DIR = "/Users/a1-6/alibaba_risk_monitor"
LOG_FILE = "logs/alert_history.json"
PRICE_CACHE = "price_cache.json"
DOCKET_CACHE = "docket_cache.json"
NEWS_CACHE = "news_cache.json"

# ===== 扫描间隔 =====
SCAN_INTERVAL_MINUTES = 480  # 价格/成交量扫描（每8小时）
NEWS_INTERVAL_MINUTES = 480  # 新闻扫描（每8小时）
DOCKET_INTERVAL_HOURS = 8    # 法律案件扫描（每8小时）

# ===== 法律文件分析 =====
# 重要法律文件类型 — 系统将重点监控以下文件
# 当出现这些类型的文件时，会触发RED/ORANGE告警
HIGH_ALERT_DOC_TYPES = [
    "MOTION_TO_DISMISS",      # 政府申请驳回 — RED
    "ADVERSE_ORDER",          # 不利裁决 — RED
    "GOVT_OPPOSITION",        # 政府反对 — ORANGE
    "TRO_MOTION",             # 禁令申请 — ORANGE
    "HEARING_SCHEDULED",      # 听证排期 — ORANGE
    "LAWSUIT_FILED",          # 新诉讼 — ORANGE
]
