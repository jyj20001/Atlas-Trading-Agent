"""Atlas Trading Agent — 全量历史 K 线回填（Futu OpenD）

从福途 OpenD 获取所有 A 股的全量历史日 K 线。
支持断点续传、中断恢复、失败隔离。

用法:
  python scripts/backfill_futu_kline.py                     # 全量
  python scripts/backfill_futu_kline.py --limit 100         # 前100只
  python scripts/backfill_futu_kline.py --batch 50          # 每批50只
  python scripts/backfill_futu_kline.py --resume            # 续传失败项
"""

import sys, os, time, logging
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "buy_stop_v3"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

import pandas as pd
from futu import OpenQuoteContext, RET_OK, KLType, AuType

from data.database import (
    _db, save_klines, count_klines,
    init_sync_status, update_sync_status,
    get_sync_status, get_pending_codes,
)
from data.kline_providers.futu_provider import FutuProvider
from data.kline_normalizer import normalized_to_kline

BATCH_SIZE = 50
MAX_RETRIES = 2


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0,
                       help="限制股票数量（0=全量）")
    parser.add_argument("--batch", type=int, default=50)
    parser.add_argument("--resume", action="store_true",
                       help="仅续传失败项")
    parser.add_argument("--reconnect", type=int, default=50,
                       help="每N只股票重连OpenD")
    args = parser.parse_args()

    from scanner.universe import build_stock_pool
    pool = build_stock_pool("A")
    all_codes = [(s.code, s.name) for s in pool]
    logging.info(f"股票池: {len(all_codes)} 只")

    if args.limit > 0:
        all_codes = all_codes[:args.limit]
        logging.info(f"限制前 {args.limit} 只")

    # 初始化状态
    init_sync_status([c for c, _ in all_codes])

    # 如果是续传模式，只处理失败/未开始的
    if args.resume:
        todo_codes = get_pending_codes(limit=args.limit or 9999)
        all_codes = [(c, "") for c in todo_codes]
        logging.info(f"续传模式: {len(all_codes)} 只待同步")

    # 连接 OpenD
    provider = FutuProvider()
    last_reconnect = 0

    def _get_ctx():
        nonlocal last_reconnect
        _ctx = OpenQuoteContext(host="127.0.0.1", port=11111, is_async_connect=False)
        last_reconnect = idx if 'idx' in dir() else 0
        return _ctx

    ctx = _get_ctx()
    logging.info("OpenD 连接成功")
    logging.info("等待 10s 让频率限制清空...")
    time.sleep(10)

    total = len(all_codes)
    success = 0
    failed = 0
    skipped = 0
    total_bars = 0
    consecutive_quota_fails = 0
    t0 = time.time()

    for idx, (code, name) in enumerate(all_codes):
        # 定期重连 OpenD（防止 session 超时）
        if idx > 0 and idx % args.reconnect == 0:
            try:
                ctx.close()
            except Exception:
                pass
            time.sleep(1)
            ctx = _get_ctx()
            logging.info(f"OpenD 重连 [{idx}/{total}]")

        # 检查是否已有足够数据
        existing = count_klines(code)
        if existing >= 4000:
            update_sync_status(code, "success", bar_count=existing)
            skipped += 1
            continue

        update_sync_status(code, "running")

        # 全量获取
        futu_code = provider._to_futu_code(code)
        if not futu_code:
            update_sync_status(code, "failed", last_error="invalid_code")
            failed += 1
            continue

        all_data = []
        page_key = None
        error_msg = ""

        # 单次请求（OpenD 限制 60次/30秒，每只股票 ~3-5个分页请求）
        try:
            while True:
                ret, data, page_key = ctx.request_history_kline(
                    code=futu_code, start="2005-01-01", end="2026-07-24",
                    ktype=KLType.K_DAY, autype=AuType.QFQ,
                    max_count=1000, page_req_key=page_key,
                )
                if ret != RET_OK:
                    error_msg = str(data)[:100] if data else "no_data"
                    break
                if data is None or (hasattr(data, 'empty') and data.empty):
                    break
                all_data.append(data)
                if page_key is None:
                    break
                if len(all_data) > 5:
                    break
                time.sleep(0.5)  # 分页间隔
        except Exception as e:
            error_msg = str(e)[:100]

        # 限速处理：等待后重连重试
        if not all_data and ("quota" in error_msg.lower()
                             or "frequency" in error_msg.lower()
                             or "no_data" in error_msg):
            wait_time = 60
            logging.warning(f"{code}: OpenD 限速, 等待 {wait_time}s 后重试 ({error_msg[:60]})")
            time.sleep(wait_time)
            for retry in range(5):
                try:
                    ctx.close()
                except Exception:
                    pass
                time.sleep(1)
                ctx = _get_ctx()
                all_data = []
                page_key = None
                while True:
                    ret, data, page_key = ctx.request_history_kline(
                        code=futu_code, start="2005-01-01", end="2026-07-24",
                        ktype=KLType.K_DAY, autype=AuType.QFQ,
                        max_count=1000, page_req_key=page_key,
                    )
                    if ret != RET_OK:
                        time.sleep(10)
                        break
                    if data is None or (hasattr(data, 'empty') and data.empty):
                        break
                    all_data.append(data)
                    if page_key is None:
                        break
                    if len(all_data) > 5:
                        break
                if all_data:
                    logging.info(f"{code}: 限速恢复, {len(all_data)*1000}+ 根")
                    break
                time.sleep(5)

        # 全部失败
        if not all_data:
            update_sync_status(code, "failed", last_error=error_msg)
            failed += 1

            # 连续配额失败检测 — 暂停等待日切
            if "quota" in error_msg.lower():
                consecutive_quota_fails += 1
                if consecutive_quota_fails >= 5:
                    logging.warning(f"连续 {consecutive_quota_fails} 只配额失败，"
                                   f"暂停回填（可能是每日配额耗尽）")
                    logging.warning(f"已完成 {success} 只，剩余待处理 {total - idx - 1} 只")
                    logging.warning(f"明日配额重置后可续传: --resume")
                    break
            else:
                consecutive_quota_fails = 0

            # 继续下一只（等 3s 间隔）
            time.sleep(3)
            continue

        # 请求间隔 3s（在 60次/30秒 限制内）
        time.sleep(3)

        # 合并并去重
        df = pd.concat(all_data, ignore_index=True)
        df = df.drop_duplicates(subset=["time_key"])
        df = df.sort_values("time_key")

        # 写入 DB（通过 normalizer）
        from data.kline_providers.base import KLineNormalized
        norm_list = []
        for _, row in df.iterrows():
            norm_list.append(KLineNormalized(
                code=code,
                trade_date=str(row["time_key"])[:10],
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=int(float(row.get("volume", 0))),
                amount=float(row.get("turnover", 0)),
                source="futu",
                adjust_type="qfq",
            ))

        # 写入 DB
        klines = [normalized_to_kline(nk) for nk in norm_list]
        # 清除旧数据 + 写新数据（全量替换）
        _db.conn.execute("DELETE FROM daily_klines WHERE code = ?", (code,))
        save_klines(code, klines, source="futu", adjust_type="qfq")
        _db.conn.commit()

        bar_count = len(klines)
        last_date = norm_list[-1].trade_date if norm_list else ""
        total_bars += bar_count
        success += 1

        update_sync_status(code, "success", bar_count=bar_count,
                          last_sync_date=last_date)

        if (idx + 1) % args.batch == 0 or idx == total - 1:
            elapsed = time.time() - t0
            rate = (idx + 1) / elapsed if elapsed > 0 else 0
            eta = (total - idx - 1) / rate if rate > 0 else 0
            logging.info(
                f"进度 [{idx+1}/{total}] "
                f"成功{success} 失败{failed} 跳过{skipped} "
                f"{total_bars}根 "
                f"ETA:{eta:.0f}s"
            )

    ctx.close()
    elapsed = time.time() - t0
    logging.info(f"\n=== 回填完成 ===")
    logging.info(f"成功: {success} | 失败: {failed} | 跳过: {skipped}")
    logging.info(f"K线总数: {total_bars} | 耗时: {elapsed:.0f}s")

    # 统计
    statuses = get_sync_status()
    total_ok = sum(1 for s in statuses if s.get("status") == "success")
    total_fail = sum(1 for s in statuses if s.get("status") == "failed")
    total_pending = sum(1 for s in statuses if s.get("status") in ("pending", "running"))
    logging.info(f"状态汇总: 成功{total_ok} / 失败{total_fail} / 待处理{total_pending}")


if __name__ == "__main__":
    main()
