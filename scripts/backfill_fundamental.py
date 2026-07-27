"""Atlas Trading Agent — 基本面数据回填

从东方财富采集最近 18 个月 A 股全量财务数据。
支持断点续传、分批、日志。

用法:
  python scripts/backfill_fundamental.py                    # 全量
  python scripts/backfill_fundamental.py --months 6        # 最近6个月
  python scripts/backfill_fundamental.py --limit 50        # 前50只测试
"""

import os, sys, time, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "buy_stop_v3"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from data.fundamental.fundamental_collector import batch_collect, collect_stock
from data.snapshot_schema import get_conn


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=18, help="采集月数")
    parser.add_argument("--limit", type=int, default=0, help="限制股票数")
    parser.add_argument("--resume", action="store_true", help="续传跳过已完成")
    args = parser.parse_args()

    from scanner.universe import build_stock_pool
    pool = build_stock_pool("A")
    codes = [s.code for s in pool]
    if args.limit:
        codes = codes[:args.limit]

    conn = get_conn()
    total = len(codes)
    success = 0
    failed = 0
    total_rows = 0
    t0 = time.time()

    for i, code in enumerate(codes):
        # 续传: 检查是否已有数据
        if args.resume:
            existing = conn.execute(
                "SELECT COUNT(*) FROM fundamental_snapshot WHERE code=?", (code,)
            ).fetchone()[0]
            if existing > 0:
                success += 1
                continue

        try:
            n = collect_stock(code)
            if n > 0:
                success += 1
                total_rows += n
            else:
                failed += 1
        except Exception as e:
            logging.error(f"{code}: {e}")
            failed += 1

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (total - i - 1) / rate if rate > 0 else 0
            logging.info(f"[{i+1}/{total}] 成功{success} 失败{failed} 数据{total_rows}行 ETA:{eta:.0f}s")

        time.sleep(0.3)

    elapsed = time.time() - t0
    logging.info(f"\n=== 回填完成 ===")
    logging.info(f"成功: {success} | 失败: {failed} | 数据行: {total_rows} | 耗时: {elapsed:.0f}s")


if __name__ == "__main__":
    main()
