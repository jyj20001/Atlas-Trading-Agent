"""Atlas Trading Agent — 基本面数据日更新

每天运行一次，检查最近已公告的财报数据并追加入库。

用法:
  python scripts/update_fundamental_daily.py
  python scripts/update_fundamental_daily.py --check-only  # 仅检查不写入
"""

import os, sys, time, logging
from datetime import date, timedelta, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "buy_stop_v3"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from data.fundamental.fundamental_collector import collect_stock
from data.snapshot_schema import get_conn


def get_latest_notice_date() -> str:
    """获取数据库中最新公告日期"""
    conn = get_conn()
    r = conn.execute(
        "SELECT MAX(publish_time) FROM fundamental_snapshot"
    ).fetchone()[0]
    return r or ""


def get_pending_codes(since_date: str) -> list[str]:
    """获取需要更新的股票（未包含给定日期后的数据）"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT code FROM fundamental_snapshot "
        "WHERE code NOT IN ("
        "  SELECT DISTINCT code FROM fundamental_snapshot "
        "  WHERE publish_time >= ?"
        ")", (since_date,)
    ).fetchall()
    if not rows:
        # 全新的：取所有股票
        from scanner.universe import build_stock_pool
        pool = build_stock_pool("A")
        return [s.code for s in pool]
    return [r[0] for r in rows]


def check_new_notices(days_back: int = 7) -> list[str]:
    """检查近期有新增公告的股票"""
    # 简化：遍历所有股票检查最新的 notice_date
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days_back)).isoformat()
    rows = conn.execute(
        "SELECT DISTINCT code FROM fundamental_snapshot "
        "WHERE publish_time >= ?", (cutoff,)
    ).fetchall()
    if rows:
        return [r[0] for r in rows]
    return []


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true", help="仅检查不写入")
    args = parser.parse_args()

    latest = get_latest_notice_date()
    logging.info(f"数据库最新公告日期: {latest or '无数据'}")

    if not latest:
        logging.warning("数据库为空，请先运行 scripts/backfill_fundamental.py")

    # 获取需要更新的股票
    since = (date.today() - timedelta(days=7)).isoformat()
    codes = get_pending_codes(since)

    if not codes:
        logging.info("所有股票已是最新数据")
        return

    logging.info(f"待更新: {len(codes)} 只")

    if args.check_only:
        return

    # 执行更新
    conn = get_conn()
    updated = 0

    for code in codes:
        n = collect_stock(code)
        if n > 0:
            updated += n
            logging.info(f"{code}: +{n} 条新数据")
        time.sleep(0.3)

    logging.info(f"更新完成: {updated} 条新数据")


if __name__ == "__main__":
    main()
