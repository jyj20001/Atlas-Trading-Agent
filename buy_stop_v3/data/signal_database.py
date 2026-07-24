"""
Atlas Trading Agent — 候选信号数据库（SQLite）

存储每日扫描产生的候选信号，用于未来统计胜率和收益。

表结构：
  signals:
    id              INTEGER PRIMARY KEY
    scan_date       TEXT    NOT NULL       — 扫描日期
    stock_code      TEXT    NOT NULL       — 股票代码
    stock_name      TEXT                   — 股票名称
    technical_score INTEGER               — 技术评分（0~100）
    fundamental_score INTEGER              — 基本面评分（0~15）
    market_score    INTEGER                — 市场评分（0~5）
    sector_score    INTEGER                — 板块评分（0~10）
    combined_score  INTEGER                — 综合评分（0~130）
    recommendation  TEXT                   — BUY_STOP / CAUTION_BUY
    breakout_stage  TEXT                   — EARLY_BREAKOUT / TRENDING / ...
    buy_stop_price  REAL                   — Buy Stop触发价格
    current_price   REAL                   — 信号日收盘价
    stop_loss       REAL                   — 止损价
    target_price    REAL                   — 目标价
    price_5d        REAL                   — 5日后价格（预留）
    price_10d       REAL                   — 10日后价格（预留）
    price_20d       REAL                   — 20日后价格（预留）
    created_at      TEXT    DEFAULT (datetime('now', 'localtime'))

    唯一约束：(scan_date, stock_code)

使用方式（在 run_scan.py 中调用）：
  from data.signal_database import save_signals
  save_signals(summary)
"""

import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

from utils.logger import logger

_DB_DIR = Path(__file__).parent
_DB_PATH = _DB_DIR / "signals.db"


def _get_conn() -> sqlite3.Connection:
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date       TEXT    NOT NULL,
            stock_code      TEXT    NOT NULL,
            stock_name      TEXT,
            technical_score INTEGER DEFAULT 0,
            fundamental_score INTEGER DEFAULT 0,
            market_score    INTEGER DEFAULT 0,
            sector_score    INTEGER DEFAULT 0,
            combined_score  INTEGER DEFAULT 0,
            recommendation  TEXT,
            breakout_stage  TEXT,
            buy_stop_price  REAL,
            current_price   REAL,
            stop_loss       REAL,
            target_price    REAL,
            price_5d        REAL,
            price_10d       REAL,
            price_20d       REAL,
            created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
            UNIQUE(scan_date, stock_code)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_signals_scan_date ON signals(scan_date)
    """)
    return conn


def save_signals(summary) -> int:
    """
    将扫描结果中的候选信号写入 signal_database。

    参数:
        summary: scanner.batch_runner.ScanSummary 对象

    返回:
        int — 写入的信号数量
    """
    if not summary.candidates:
        return 0

    today = date.today().isoformat()
    conn = _get_conn()
    count = 0

    for result in summary.candidates:
        o = result.output
        s = o.signal if o else None
        code = result.stock.code
        name = result.stock.name

        try:
            conn.execute("""
                INSERT OR REPLACE INTO signals
                (scan_date, stock_code, stock_name,
                 technical_score, fundamental_score,
                 market_score, sector_score, combined_score,
                 recommendation, breakout_stage,
                 buy_stop_price, current_price, stop_loss, target_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                today, code, name,
                s.total_score if s else 0,
                o.fundamental_score,
                o.market_score,
                o.sector_score,
                o.combined_score,
                o.recommendation,
                o.breakout_stage,
                s.breakout_price if s else None,
                s.price if s else None,
                s.stop_loss if s else None,
                s.target if s else None,
            ))
            count += 1
        except Exception as e:
            logger.debug(f"写入信号失败 {code}: {e}")

    conn.commit()
    conn.close()

    if count > 0:
        logger.info(f"信号数据库: 写入 {count} 条候选 ({today})")

    return count


def query_signals(scan_date: Optional[str] = None,
                  stock_code: Optional[str] = None,
                  limit: int = 50) -> list[dict]:
    """
    查询信号历史。

    参数:
        scan_date: 按日期筛选（YYYY-MM-DD）
        stock_code: 按股票代码筛选
        limit: 返回条数

    返回:
        list[dict]
    """
    conn = _get_conn()
    where = []
    params = []

    if scan_date:
        where.append("scan_date = ?")
        params.append(scan_date)
    if stock_code:
        where.append("stock_code = ?")
        params.append(stock_code)

    sql = "SELECT * FROM signals"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY scan_date DESC, combined_score DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    columns = [
        "id", "scan_date", "stock_code", "stock_name",
        "technical_score", "fundamental_score",
        "market_score", "sector_score", "combined_score",
        "recommendation", "breakout_stage",
        "buy_stop_price", "current_price", "stop_loss", "target_price",
        "price_5d", "price_10d", "price_20d", "created_at",
    ]
    return [dict(zip(columns, row)) for row in rows]


def get_stats() -> dict:
    """获取信号数据库统计"""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    dates = conn.execute(
        "SELECT scan_date, COUNT(*) FROM signals GROUP BY scan_date ORDER BY scan_date"
    ).fetchall()
    conn.close()
    return {
        "total_signals": total,
        "scan_dates": [{"date": r[0], "count": r[1]} for r in dates],
    }
