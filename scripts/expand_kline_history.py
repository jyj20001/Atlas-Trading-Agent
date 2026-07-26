"""Atlas Trading Agent — 历史K线批量扩展

目标: 将每只股票的 K 线从 ~800 根扩展到 ~2000 根。
覆盖: 2018-01-01 以后的交易日数据。

策略:
  - 已有 800 日缓存的股票: 增量补充（INSERT OR REPLACE 天然去重）
  - 无缓存的股票: 全量获取
  - 科创板/北交所: 最多尝试 1500 根（API 限制）
"""

import sys, os, time, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "buy_stop_v3"))

import logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

from data.market_fetcher import fetch_klines
from data.database import count_klines, get_db_stats, _db
from scanner.universe import build_stock_pool

EXPECTED_DAYS = 2000
SAMPLE_CODES = ["600000", "000001", "300750"]
LIMIT = 200  # 先扩展前 200 只（基线使用）


def get_all_codes() -> list[tuple[str, str]]:
    """获取需要扩展的股票"""
    pool = build_stock_pool("A")
    logging.info(f"股票池: {len(pool)} 只, 扩展前 {LIMIT} 只")
    return [(s.code, s.name) for s in pool[:LIMIT]]


def expand_single(code: str, name: str,
                   target_days: int = EXPECTED_DAYS) -> dict:
    """扩展单只股票的历史K线"""
    before = count_klines(code)
    result = {"code": code, "name": name, "before": before,
              "after": 0, "success": False, "msg": ""}

    try:
        # fetch_klines 会检查缓存:
        #   - 缓存 >= target_days 且最新日期匹配 → 直接返回
        #   - 缓存不足 → 从 API 获取 target_days 根
        # save_klines 内部用 INSERT OR REPLACE，不会重复
        klines = fetch_klines(code, days=target_days)
    except Exception as e:
        result["msg"] = f"异常: {e}"
        return result

    if not klines or len(klines) < target_days:
        # 尝试用更少天数
        for fallback_days in [1500, 1200, 1000]:
            try:
                klines = fetch_klines(code, days=fallback_days)
                if klines and len(klines) >= target_days * 0.7:
                    break
            except Exception:
                continue

    if not klines:
        result["msg"] = "无数据"
        return result

    after = count_klines(code)
    result["after"] = after
    result["success"] = True
    result["msg"] = f"{before} → {after} 根"
    return result


def verify_sample():
    """验证样本股票覆盖到 2018 以前"""
    logging.info("验证样本股票...")
    for code in SAMPLE_CODES:
        klines = fetch_klines(code, days=EXPECTED_DAYS)
        if klines:
            earliest = klines[0].date
            logging.info(f"  {code}: 最早 {earliest} (共 {len(klines)} 根)")
            ok = earliest <= "2018-01-01"
            logging.info(f"  → {'✅' if ok else '❌'} {'达标' if ok else '需补充'}")
        else:
            logging.info(f"  {code}: ❌ 获取失败")


def main():
    codes = get_all_codes()
    logging.info(f"开始历史 K 线扩展: {len(codes)} 只, target={EXPECTED_DAYS} 根")

    success = 0
    failed = 0
    skipped = 0
    total_before = 0
    total_after = 0
    t0 = time.time()

    for idx, (code, name) in enumerate(codes):
        before = count_klines(code)
        total_before += before

        if before >= EXPECTED_DAYS:
            skipped += 1
            total_after += before
            continue

        result = expand_single(code, name)
        if result["success"]:
            success += 1
        else:
            failed += 1

        total_after += result["after"]

        if (idx + 1) % 200 == 0:
            elapsed = time.time() - t0
            rate = (idx + 1) / elapsed
            eta = (len(codes) - idx - 1) / rate if rate > 0 else 0
            logging.info(f"  进度 [{idx+1}/{len(codes)}] "
                        f"成功{success} 失败{failed} 跳过{skipped} "
                        f"ETA:{eta:.0f}s")

    elapsed = time.time() - t0
    avg_len = total_after / len(codes) if codes else 0

    # 验证样本
    verify_sample()

    # 数据库统计
    stats = get_db_stats()

    # 报告
    lines = []
    w = lambda s="": lines.append(s)
    w("# Atlas Trading Agent — Historical K-Line Expansion Report")
    w("")
    w(f"**日期:** {time.strftime('%Y-%m-%d %H:%M')}")
    w(f"**目标:** 每只股票 ≥ {EXPECTED_DAYS} 根日 K 线 (覆盖 ~2018)")
    w("")
    w("## 执行统计")
    w("")
    w("| 指标 | 值 |")
    w("|------|-----:|")
    w(f"| 股票总数 | {len(codes)} |")
    w(f"| 成功扩展 | {success} |")
    w(f"| 失败 | {failed} |")
    w(f"| 跳过（已有足够数据） | {skipped} |")
    w(f"| 平均K线长度 | {avg_len:.0f} 根 |")
    w(f"| 总耗时 | {elapsed:.0f} 秒 |")
    w("")
    w("## 数据库状态")
    w("")
    w(f"| 指标 | 值 |")
    w(f"|------|-----:|")
    w(f"| 代码数 | {stats['total_codes']} |")
    w(f"| K线总数 | {stats['total_rows']} |")
    w("")

    w("## 样本验证")
    w("")
    for code in SAMPLE_CODES:
        try:
            klines = fetch_klines(code, days=EXPECTED_DAYS)
            if klines:
                earliest = klines[0].date
                latest = klines[-1].date
                ok = "✅" if earliest <= "2018-01-01" else "❌"
                w(f"| {code} | {earliest} ~ {latest} | {len(klines)}根 | {ok} |")
        except Exception as e:
            w(f"| {code} | 失败: {e} | - | ❌ |")
    w("")

    rp = os.path.expanduser(
        "~/Atlas-Trading-Agent/docs/HISTORICAL_KLINE_EXPANSION_REPORT.md"
    )
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    with open(rp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n{'='*60}")
    print(f"📊 K-Line 扩展完成")
    print(f"{'='*60}")
    print(f"  成功: {success} | 失败: {failed} | 跳过: {skipped}")
    print(f"  扩展前: {total_before} 根")
    print(f"  扩展后: {total_after} 根")
    print(f"  平均: {avg_len:.0f} 根/股")
    print(f"  耗时: {elapsed:.0f} 秒")
    print(f"  报告: docs/HISTORICAL_KLINE_EXPANSION_REPORT.md")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
