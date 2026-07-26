"""Atlas Trading Agent — Historical Snapshot 批量回填

一次性回填 market_snapshot 和 sector_snapshot 历史数据。
从腾讯 API 获取全历史日 K 线，写入 snapshot 表。

用法:
  python scripts/backfill_snapshots.py           # 回填所有（5年）
  python scripts/backfill_snapshots.py --days 60 # 仅最近 60 天

注意:
  首次运行需约 30-60 秒（25 个指数 × 少量 API 调用）。
  announcement_snapshot 需通过 cninfo_snapshot_collector 单独采集。
"""

import sys
import os
import time
import json
from datetime import date, datetime, timedelta

# 确保导入路径正确
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "buy_stop_v3"))

from data.snapshot_schema import get_conn, init_schema, SNAPSHOT_VERSION, TABLE_NAMES
from data.http_client import get_json
from utils.logger import logger
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ── 指数映射 ──

MARKET_INDEXES = {
    "000300": {"name": "沪深300", "prefix": "sh"},
    "000001": {"name": "上证指数", "prefix": "sh"},
    "399006": {"name": "创业板指", "prefix": "sz"},
}

# 板块代码（对应 sector_scorer.py 中的 sz980xxx 系列）
SECTOR_INDEXES = [
    ("sz980017", "半导体"), ("sz980021", "人工智能"), ("sz980022", "计算机"),
    ("sz980024", "通信"), ("sz980014", "电子"),
    ("sz980054", "新能源汽车"), ("sz980050", "新能源"),
    ("sz980036", "医药"), ("sz980038", "生物医药"),
    ("sz980060", "食品饮料"), ("sz980062", "白酒"),
    ("sz980064", "家电"), ("sz980070", "房地产"),
    ("sz980080", "银行"), ("sz980082", "券商"),
    ("sz980084", "保险"), ("sz980090", "军工"),
    ("sz980100", "机械"), ("sz980110", "化工"),
    ("sz980120", "有色"), ("sz980130", "钢铁"),
    ("sz980140", "煤炭"), ("sz980150", "电力"),
    ("sz980160", "交通运输"), ("sz980170", "建筑"),
    ("sz980180", "建材"), ("sz980190", "农业"),
    ("sz980200", "传媒"),
]

TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def _fetch_index_klines(index_code: str, days: int = 2000) -> list[dict]:
    """从腾讯 API 获取指数日 K 线
    
    支持格式:
      - "000300" (市场指数, 自动加 sh/sz 前缀)
      - "sz980017" (板块指数, 自带前缀)
    """
    # 解析代码: 已有前缀则直接用，否则从 MARKET_INDEXES 查找
    if index_code.startswith(("sh", "sz", "bj")):
        param = f"{index_code},day,,,{days},qfq"
        stock_key = index_code
    else:
        info = MARKET_INDEXES.get(index_code, {})
        prefix = info.get("prefix", "sh")
        param = f"{prefix}{index_code},day,,,{days},qfq"
        stock_key = f"{prefix}{index_code}"

    try:
        data = get_json(TENCENT_URL, {"param": param}, retries=2, timeout=15)
    except Exception as e:
        logger.warning(f"获取 {index_code} 失败: {e}")
        return []

    stock_data = data.get("data", {}).get(stock_key, {})
    raw = stock_data.get("qfqday") or stock_data.get("day")
    if not raw:
        logger.warning(f"{index_code}: 无 K 线数据")
        return []

    klines = []
    for row in raw:
        if len(row) < 6:
            continue
        try:
            klines.append({
                "date": str(row[0]),
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": int(float(row[5])),
            })
        except (ValueError, IndexError):
            continue
    return klines


def _compute_ma(closes: list, period: int) -> float:
    if len(closes) < period:
        return 0.0
    return round(sum(closes[-period:]) / period, 2)


# ══════════════════════════════════════════════════════════════
# Market Snapshot 回填
# ══════════════════════════════════════════════════════════════

def backfill_market(days: int = 2000) -> dict:
    """回填三大指数日数据到 market_snapshot"""
    conn = get_conn()
    total = 0

    for code, info in MARKET_INDEXES.items():
        klines = _fetch_index_klines(code, days=days)
        if not klines:
            logger.warning(f"跳过 {info['name']} ({code})")
            continue

        inserted = 0
        for i, k in enumerate(klines):
            close = k["close"]
            # 计算到当前 bar 为止的 MA
            closes_to_date = [klines[j]["close"] for j in range(i + 1)]
            ma20 = _compute_ma(closes_to_date, 20) if len(closes_to_date) >= 20 else None
            ma50 = _compute_ma(closes_to_date, 50) if len(closes_to_date) >= 50 else None

            td = k["date"]
            # available_time = 次日 09:00（收盘后才能用）
            try:
                dt = datetime.strptime(td, "%Y-%m-%d")
                avail = (dt + timedelta(days=1)).strftime("%Y-%m-%d 09:00:00")
            except ValueError:
                avail = td + " 09:00:00"

            conn.execute(
                "INSERT OR IGNORE INTO market_snapshot "
                "(index_code, index_name, trade_date, publish_time, available_time, "
                "open, close, high, low, volume, ma20, ma50, source, snapshot_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (code, info["name"], td, avail, avail,
                 k["open"], close, k["high"], k["low"], k["volume"],
                 ma20, ma50, "tencent", SNAPSHOT_VERSION)
            )
            inserted += 1
            total += 1

        conn.commit()
        logger.info(f"  {info['name']}: {inserted} 行 ({klines[0]['date']} ~ {klines[-1]['date']})")
        time.sleep(0.5)  # 请求间隔

    return {"table": "market_snapshot", "total_rows": total}


# ══════════════════════════════════════════════════════════════
# Sector Snapshot 回填
# ══════════════════════════════════════════════════════════════

def backfill_sectors(days: int = 2000) -> dict:
    """回填板块指数日数据到 sector_snapshot"""
    conn = get_conn()
    total = 0

    for idx_code, sector_name in SECTOR_INDEXES:
        klines = _fetch_index_klines(idx_code, days=days)
        if not klines:
            logger.warning(f"跳过 {sector_name} ({idx_code})")
            continue

        inserted = 0
        for i, k in enumerate(klines):
            close = k["close"]
            closes_to_date = [klines[j]["close"] for j in range(i + 1)]

            # 5 日收益率
            return_5d = 0.0
            if i >= 5:
                return_5d = round((close - klines[i - 5]["close"]) / klines[i - 5]["close"] * 100, 2)

            # 1 日收益率
            return_1d = 0.0
            if i >= 1:
                return_1d = round((close - klines[i - 1]["close"]) / klines[i - 1]["close"] * 100, 2)

            ma20 = _compute_ma(closes_to_date, 20) if len(closes_to_date) >= 20 else None

            td = k["date"]
            try:
                dt = datetime.strptime(td, "%Y-%m-%d")
                avail = (dt + timedelta(days=1)).strftime("%Y-%m-%d 09:00:00")
            except ValueError:
                avail = td + " 09:00:00"

            conn.execute(
                "INSERT OR IGNORE INTO sector_snapshot "
                "(index_code, sector_name, trade_date, publish_time, available_time, "
                "close, return_1d, return_5d, volume, ma20, source, snapshot_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (idx_code, sector_name, td, avail, avail,
                 close, return_1d, return_5d, k["volume"],
                 ma20, "tencent", SNAPSHOT_VERSION)
            )
            inserted += 1
            total += 1

        conn.commit()
        logger.info(f"  {sector_name}: {inserted} 行 ({klines[0]['date']} ~ {klines[-1]['date']})")
        time.sleep(0.5)

    return {"table": "sector_snapshot", "total_rows": total}


# ══════════════════════════════════════════════════════════════
# CNINFO 公告回填
# ══════════════════════════════════════════════════════════════

def backfill_cninfo(start_date: str, end_date: str) -> dict:
    """回填 CNINFO 公告到 announcement_snapshot（依赖 cninfo_snapshot_collector）"""
    try:
        from data.cninfo_snapshot_collector import run_collector
        result = run_collector(start_date, end_date)
        logger.info(f"  CNINFO: {result}")
        return result
    except Exception as e:
        logger.warning(f"CNINFO 采集失败 (可能无网络): {e}")
        return {"inserted": 0, "skipped_duplicates": 0, "failures": 1, "detail": {}}


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Historical Snapshot 批量回填")
    parser.add_argument("--days", type=int, default=2000, help="回填天数 (默认 2000 ~8年)")
    parser.add_argument("--market-only", action="store_true", help="仅回填市场指数")
    parser.add_argument("--sector-only", action="store_true", help="仅回填板块指数")
    args = parser.parse_args()

    init_schema()
    logger.info(f"开始回填 historical snapshot (days={args.days})")

    results = {}

    if not args.sector_only:
        logger.info("\n=== Market Snapshot ===")
        results["market"] = backfill_market(args.days)

    if not args.market_only:
        logger.info("\n=== Sector Snapshot ===")
        results["sector"] = backfill_sectors(args.days)

    logger.info(f"\n回填完成: {json.dumps(results, ensure_ascii=False)}")

    # 输出统计
    from data.snapshot_schema import get_table_count, TABLE_NAMES
    for t in ["market_snapshot", "sector_snapshot"]:
        cnt = get_table_count(t)
        logger.info(f"  {t}: {cnt} 行")
