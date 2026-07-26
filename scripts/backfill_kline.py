"""Atlas Trading Agent — 批量回填历史K线（东方财富）

回填前 200 只股票的全量历史 K 线（东方财富数据源）。
已有腾讯缓存的股票做增量合并。

用法:
  python scripts/backfill_kline.py              # 回填前200只
  python scripts/backfill_kline.py --limit 50   # 只回填50只测试
"""

import sys, os, time, logging
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "buy_stop_v3"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

LIMIT = 200


def main():
    from scanner.universe import build_stock_pool
    from data.database import count_klines, load_klines, save_klines, _db
    from data.kline_providers import fetch_from_chain
    from data.kline_normalizer import merge_and_dedup

    pool = [(s.code, s.name) for s in build_stock_pool("A")[:LIMIT]]
    logging.info(f"回填 {len(pool)} 只股票的历史K线...")

    success = 0
    failed = 0
    skipped = 0
    t0 = time.time()

    for idx, (code, name) in enumerate(pool):
        before = count_klines(code)

        if before >= 2000:
            skipped += 1
            continue

        try:
            nklines = fetch_from_chain(code, max_count=2000, min_bars=200)
        except Exception:
            failed += 1
            continue

        if not nklines:
            failed += 1
            continue

        # 增量合并缓存
        existing = load_klines(code, limit=9999)
        merged = merge_and_dedup(existing, nklines)

        # 替换缓存
        _db.conn.execute("DELETE FROM daily_klines WHERE code = ?", (code,))
        save_klines(code, merged, source=nklines[0].source,
                    adjust_type=nklines[0].adjust_type)

        after = count_klines(code)
        success += 1

        if (idx + 1) % 25 == 0:
            elapsed = time.time() - t0
            logging.info(f"  进度 [{idx+1}/{len(pool)}] "
                        f"成功{success} 失败{failed} 跳过{skipped} "
                        f"累计{after}根 "
                        f"ETA:{elapsed/(idx+1)*(len(pool)-idx-1):.0f}s")

    elapsed = time.time() - t0
    logging.info(f"完成: {success}成功 {failed}失败 {skipped}跳过 "
                f"耗时{elapsed:.0f}s")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=LIMIT)
    args = parser.parse_args()
    LIMIT = args.limit
    main()
