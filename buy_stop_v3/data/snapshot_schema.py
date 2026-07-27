"""Atlas Trading Agent — Historical Snapshot Schema

管理 historical.db 中的 4 张历史快照表。

数据库: data/historical.db（独立于 market.db）

表结构:
  announcement_snapshot  — 公告快照（业绩预告/快报/合同/回购）
  fundamental_snapshot   — 基本面指标快照（营收/利润/ROE）
  sector_snapshot        — 板块指数快照（行业指数日数据）
  market_snapshot        — 市场环境快照（三大指数日数据）

每条记录包含:
  publish_time     — 数据实际发布时间（ISO datetime）
  available_time   — 数据对交易决策可用的时间（ISO datetime）
  snapshot_version — 快照版本标识
"""

import sqlite3
from pathlib import Path
from typing import Optional

from utils.logger import logger

# ── 数据库路径 ──
_DB_DIR = Path(__file__).parent  # data/
_DB_PATH = _DB_DIR / "historical.db"

# ── 快照版本 ──
SNAPSHOT_VERSION = "1.0.0"

# ── 建表 SQL ──

_SQL_ANNOUNCEMENT_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS announcement_snapshot (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    publish_time    TEXT NOT NULL,           -- ISO datetime 公告发布时间
    available_time  TEXT NOT NULL,           -- ISO datetime 数据可用时间
    announce_type   TEXT NOT NULL,           -- 类型: performance_forecast / performance_report / major_contract / buyback

    -- 业绩预告/快报字段
    report_type     TEXT DEFAULT '',         -- 预增/预减/扭亏/首亏/预警
    forecast_type   TEXT DEFAULT '',         -- 业绩预告 / 业绩快报
    net_profit_lower REAL,
    net_profit_upper REAL,
    change_pct_lower REAL,
    change_pct_upper REAL,

    -- 合同/回购字段
    title           TEXT DEFAULT '',
    keyword         TEXT DEFAULT '',

    -- 元数据
    source          TEXT DEFAULT 'cninfo',
    snapshot_version TEXT DEFAULT '1.0.0',
    collected_at    TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(code, publish_time, announce_type)
);
CREATE INDEX IF NOT EXISTS idx_ann_available
    ON announcement_snapshot(available_time);
CREATE INDEX IF NOT EXISTS idx_ann_code
    ON announcement_snapshot(code);
"""

_SQL_FUNDAMENTAL_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS fundamental_snapshot (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    fiscal_period   TEXT NOT NULL,           -- 财报所属期 e.g. "2026Q2"
    publish_time    TEXT NOT NULL,           -- ISO datetime 财报发布时间
    available_time  TEXT NOT NULL,           -- ISO datetime 数据可用时间

    -- 利润表
    revenue         REAL,
    revenue_yoy     REAL,
    net_profit      REAL,
    net_profit_yoy  REAL,

    -- 资产负债表
    total_assets    REAL,
    total_liab      REAL,
    equity          REAL,

    -- 盈利能力
    roe             REAL,
    gross_margin    REAL,
    net_margin      REAL,

    -- 元数据
    source          TEXT DEFAULT 'cninfo',
    snapshot_version TEXT DEFAULT '1.0.0',
    collected_at    TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fund_unique
    ON fundamental_snapshot(code, fiscal_period, source);
CREATE INDEX IF NOT EXISTS idx_fund_available
    ON fundamental_snapshot(available_time);
CREATE INDEX IF NOT EXISTS idx_fund_code
    ON fundamental_snapshot(code);
"""

_SQL_SECTOR_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS sector_snapshot (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    index_code      TEXT NOT NULL,           -- 板块指数代码 e.g. "sz980017"
    sector_name     TEXT NOT NULL,
    trade_date      TEXT NOT NULL,           -- 交易日 YYYY-MM-DD
    publish_time    TEXT NOT NULL,           -- ISO datetime = 当日收盘时间
    available_time  TEXT NOT NULL,           -- ISO datetime = 收盘后可用时间

    close           REAL,
    return_1d       REAL,
    return_5d       REAL,
    volume          REAL,
    ma20            REAL,

    -- 元数据
    source          TEXT DEFAULT 'tencent',
    snapshot_version TEXT DEFAULT '1.0.0',
    collected_at    TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_sector_available
    ON sector_snapshot(available_time);
CREATE INDEX IF NOT EXISTS idx_sector_code
    ON sector_snapshot(index_code);
CREATE INDEX IF NOT EXISTS idx_sector_trade_date
    ON sector_snapshot(trade_date);
"""

_SQL_MARKET_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS market_snapshot (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    index_code      TEXT NOT NULL,           -- 指数代码: "000300"/"000001"/"399006"
    index_name      TEXT NOT NULL,           -- 指数名称
    trade_date      TEXT NOT NULL,           -- 交易日 YYYY-MM-DD
    publish_time    TEXT NOT NULL,           -- ISO datetime = 当日收盘时间
    available_time  TEXT NOT NULL,           -- ISO datetime = 收盘后可用时间

    open            REAL,
    close           REAL,
    high            REAL,
    low             REAL,
    volume          REAL,
    ma20            REAL,
    ma50            REAL,
    trend_score     INTEGER,
    market_status   TEXT,

    -- 元数据
    source          TEXT DEFAULT 'tencent',
    snapshot_version TEXT DEFAULT '1.0.0',
    collected_at    TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_market_available
    ON market_snapshot(available_time);
CREATE INDEX IF NOT EXISTS idx_market_code
    ON market_snapshot(index_code);
CREATE INDEX IF NOT EXISTS idx_market_trade_date
    ON market_snapshot(trade_date);
"""

_ALL_SQL = [
    _SQL_ANNOUNCEMENT_SNAPSHOT,
    _SQL_FUNDAMENTAL_SNAPSHOT,
    _SQL_SECTOR_SNAPSHOT,
    _SQL_MARKET_SNAPSHOT,
]

# ── 采集元数据表 ──

_SQL_COLLECTION_TRACKING = """
CREATE TABLE IF NOT EXISTS collection_tracking (
    collector_name  TEXT PRIMARY KEY,
    last_run_at     TEXT NOT NULL,
    last_success_at TEXT,
    status          TEXT DEFAULT 'ok',
    stats_json      TEXT DEFAULT '{}'
);
"""

_ALL_SQL.append(_SQL_COLLECTION_TRACKING)


# ── 连接管理 ──

class HistoricalDB:
    """historical.db 单例管理"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._conn = None
        return cls._instance

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            _DB_DIR.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(_DB_PATH))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=OFF")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._init_schema()
            logger.info(f"历史快照数据库: {_DB_PATH}")
        return self._conn

    def _init_schema(self):
        for sql in _ALL_SQL:
            self._conn.executescript(sql)
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def reset_db(self):
        """删除所有表并重建（仅测试用）"""
        self.close()
        if _DB_PATH.exists():
            _DB_PATH.unlink()
        # 重新初始化
        _ = self.conn

    @property
    def db_path(self) -> str:
        return str(_DB_PATH)


_db = HistoricalDB()


# ── 公开接口 ──

def get_conn() -> sqlite3.Connection:
    """获取数据库连接"""
    return _db.conn


def get_db_path() -> str:
    return _db.db_path


def init_schema():
    """初始化/重建所有表结构"""
    conn = _db.conn  # 确保连接已建立
    for sql in _ALL_SQL:
        conn.executescript(sql)
    conn.commit()


def table_exists(name: str) -> bool:
    """检查表是否存在"""
    cur = _db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,)
    )
    return cur.fetchone() is not None


def get_table_count(name: str) -> int:
    """获取表记录数"""
    try:
        cur = _db.conn.execute(f"SELECT COUNT(*) FROM {name}")
        return cur.fetchone()[0]
    except Exception:
        return 0


TABLE_NAMES = [
    "announcement_snapshot",
    "fundamental_snapshot",
    "sector_snapshot",
    "market_snapshot",
    "collection_tracking",
]

# 仅数据表（不含元数据表，用于列校验）
DATA_TABLE_NAMES = [
    "announcement_snapshot",
    "fundamental_snapshot",
    "sector_snapshot",
    "market_snapshot",
]
