"""
Atlas Trading Agent — 本地行情数据库（SQLite）

功能：
  - 缓存日K线数据，避免重复下载
  - 支持增量更新（首次完整下载，日常只补充最新交易日）
  - 自动建表
  - 查询/写入/批量写入接口

表结构：
  daily_klines:
    code         TEXT NOT NULL
    trade_date   TEXT NOT NULL
    open         REAL
    high         REAL
    low          REAL
    close        REAL
    volume       REAL
    amount       REAL
    source       TEXT DEFAULT 'tencent'
    updated_at   TEXT DEFAULT (datetime('now'))
    PRIMARY KEY (code, trade_date)
"""

import sqlite3
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from utils.logger import logger

# ── 数据库路径 ──
_DB_DIR = Path(__file__).parent  # data/
_DB_PATH = _DB_DIR / "market.db"

# ── 建表 SQL ──
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS daily_klines (
    code         TEXT NOT NULL,
    trade_date   TEXT NOT NULL,
    open         REAL,
    high         REAL,
    low          REAL,
    close        REAL,
    volume       REAL,
    amount       REAL DEFAULT 0,
    source       TEXT DEFAULT 'tencent',
    updated_at   TEXT DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (code, trade_date)
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_daily_klines_code ON daily_klines(code);
"""


# ── 连接管理 ──

class Database:
    """行情数据库单例封装"""

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
            self._conn.executescript(_CREATE_TABLE)
            self._conn.executescript(_CREATE_INDEX)
            self._conn.commit()
            logger.debug(f"行情数据库: {_DB_PATH}")
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


_db = Database()


# ── 公开接口 ──

def get_latest_date(code: str) -> Optional[str]:
    """获取缓存中某只股票的最新交易日"""
    cur = _db.conn.execute(
        "SELECT MAX(trade_date) FROM daily_klines WHERE code = ?", (code,)
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def count_klines(code: str) -> int:
    """获取缓存中某只股票的K线数量"""
    cur = _db.conn.execute(
        "SELECT COUNT(*) FROM daily_klines WHERE code = ?", (code,)
    )
    return cur.fetchone()[0]


def load_klines(code: str, limit: int = 250) -> list[dict]:
    """从缓存加载K线（按日期降序）"""
    cur = _db.conn.execute(
        "SELECT trade_date, open, high, low, close, volume, amount, source "
        "FROM daily_klines WHERE code = ? "
        "ORDER BY trade_date DESC LIMIT ?",
        (code, limit),
    )
    rows = cur.fetchall()
    return [
        {
            "date": r[0], "open": r[1], "high": r[2],
            "low": r[3], "close": r[4], "volume": r[5],
            "amount": r[6], "source": r[7],
        }
        for r in reversed(rows)  # 转回正序
    ]


def save_klines(code: str, klines, source: str = "tencent"):
    """批量写入K线（INSERT OR REPLACE）"""

    from data.types import KLine

    if not klines:
        return

    rows = []
    for k in klines:
        rows.append((
            code, k.date, k.open, k.high, k.low,
            k.close, float(k.volume), float(k.amount or 0), source,
        ))

    _db.conn.executemany(
        "INSERT OR REPLACE INTO daily_klines "
        "(code, trade_date, open, high, low, close, volume, amount, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    _db.conn.commit()
    logger.debug(f"缓存 {code}: {len(rows)} 根K线 ({source})")


def get_cached_and_missing(code: str, needed: int = 250
                           ) -> tuple[list[dict], Optional[str]]:
    """
    获取缓存状态：
      返回 (已缓存K线, 最新交易日)
      如果缓存不足，latest_date 可用于增量请求
    """
    cached = load_klines(code, limit=needed)
    latest = get_latest_date(code)
    return cached, latest


def get_db_stats() -> dict:
    """获取缓存统计"""
    cur = _db.conn.execute(
        "SELECT code, COUNT(*) as cnt, MAX(trade_date) as last "
        "FROM daily_klines GROUP BY code ORDER BY cnt DESC"
    )
    rows = cur.fetchall()
    total_codes = len(rows)
    total_rows = sum(r[1] for r in rows)
    return {
        "total_codes": total_codes,
        "total_rows": total_rows,
        "codes": [{"code": r[0], "count": r[1], "latest": r[2]} for r in rows],
    }


def KLine_to_dict(kline) -> list:
    """将 KLine 对象转为 (date, open, close, high, low, volume) 元组"""
    return [kline.date, kline.open, kline.close, kline.high, kline.low, kline.volume]

    # 为类型提示导入
