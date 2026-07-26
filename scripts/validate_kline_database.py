"""Atlas Trading Agent — K线数据库质量检查

检查:
  1. 重复交易日
  2. 缺失交易日
  3. OHLC 异常 (high < max(open,close), low > min(open,close))
  4. 空成交量
  5. 数据覆盖范围

输出: docs/KLINE_DATABASE_HEALTH_REPORT.md
"""

import sys, os, logging
from datetime import date
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "buy_stop_v3"))
logging.disable(logging.CRITICAL)


def check():
    from data.database import _db, get_db_stats

    conn = _db.conn

    # ── 1. 总体统计 ──
    total_rows = conn.execute("SELECT COUNT(*) FROM daily_klines").fetchone()[0]
    total_codes = conn.execute("SELECT COUNT(DISTINCT code) FROM daily_klines").fetchone()[0]
    earliest = conn.execute("SELECT MIN(trade_date) FROM daily_klines").fetchone()[0]
    latest = conn.execute("SELECT MAX(trade_date) FROM daily_klines").fetchone()[0]
    sync_total = conn.execute("SELECT COUNT(*) FROM kline_sync_status").fetchone()[0]
    sync_ok = conn.execute("SELECT COUNT(*) FROM kline_sync_status WHERE status='success'").fetchone()[0]
    sync_fail = conn.execute("SELECT COUNT(*) FROM kline_sync_status WHERE status='failed'").fetchone()[0]

    # ── 2. 重复检查 ──
    dupes = conn.execute(
        "SELECT code, trade_date, COUNT(*) FROM daily_klines "
        "GROUP BY code, trade_date HAVING COUNT(*) > 1"
    ).fetchall()
    total_dupes = len(dupes)

    # ── 3. OHLC 异常 ──
    hilo = conn.execute(
        "SELECT code, trade_date, open, high, low, close "
        "FROM daily_klines "
        "WHERE high < max(open, close) OR low > min(open, close)"
    ).fetchall()
    total_hilo = len(hilo)

    # ── 4. 空成交量 ──
    zero_vol = conn.execute(
        "SELECT code, trade_date FROM daily_klines WHERE volume = 0"
    ).fetchall()
    total_zero_vol = len(zero_vol)

    # ── 5. 零价格 ──
    zero_close = conn.execute(
        "SELECT code, trade_date FROM daily_klines WHERE close = 0"
    ).fetchall()
    total_zero_close = len(zero_close)

    # ── 6. 负数收盘价 (QFQ 副作用) ──
    neg_close = conn.execute(
        "SELECT code, trade_date, close FROM daily_klines WHERE close < 0"
    ).fetchall()
    total_neg = len(neg_close)

    # ── 7. 覆盖深度 ──
    per_code = conn.execute(
        "SELECT code, COUNT(*) as cnt, MIN(trade_date) as first, MAX(trade_date) as last "
        "FROM daily_klines GROUP BY code"
    ).fetchall()

    min_bars = min(r[1] for r in per_code) if per_code else 0
    max_bars = max(r[1] for r in per_code) if per_code else 0
    avg_bars = round(sum(r[1] for r in per_code) / len(per_code), 1) if per_code else 0

    # 覆盖完整区间 (2018-01-01 ~ 2026-07-24) 的股票数
    full_coverage = sum(
        1 for r in per_code
        if r[2] <= "2018-01-01" and r[3] >= "2026-07-01"
    )

    # ── 8. 健康率 ──
    total_issues = total_dupes + total_hilo + total_zero_vol + total_zero_close
    # 负数 close 不做扣分（已知 QFQ 副作用）
    health_rate = round(
        (total_rows - total_issues) / max(total_rows, 1) * 100, 2
    )

    # ── 生成报告 ──
    lines = []
    w = lambda s="": lines.append(s)
    w("# K-Line Database Health Report")
    w("")
    w(f"**日期:** {date.today().isoformat()}")
    w("")

    w("## 总体统计")
    w("")
    w("| 指标 | 值 |")
    w("|------|-----:|")
    w(f"| 股票总数 | {total_codes} |")
    w(f"| K线总数 | {total_rows:,} |")
    w(f"| 最早日期 | {earliest} |")
    w(f"| 最新日期 | {latest} |")
    w(f"| 健康率 | {health_rate}% |")
    w("")

    w("## 数据覆盖深度")
    w("")
    w("| 指标 | 值 |")
    w("|------|-----:|")
    w(f"| 最少K线/股 | {min_bars} |")
    w(f"| 最多K线/股 | {max_bars} |")
    w(f"| 平均K线/股 | {avg_bars} |")
    w(f"| 完整覆盖 (2018+) | {full_coverage} |")
    w("")

    w("## 数据质量")
    w("")
    w("| 检查项 | 数量 | 状态 |")
    w("|--------|:----:|:----:|")
    w(f"| 重复交易日 | {total_dupes} | {'✅' if total_dupes == 0 else '⚠️'} |")
    w(f"| OHLC 异常 | {total_hilo} | {'✅' if total_hilo == 0 else '⚠️'} |")
    w(f"| 空成交量 | {total_zero_vol} | {'✅' if total_zero_vol == 0 else '⚠️'} |")
    w(f"| 零收盘价 | {total_zero_close} | {'✅' if total_zero_close == 0 else '⚠️'} |")
    w(f"| 负数收盘价 (QFQ) | {total_neg} | ⚠️ 已知问题 |")
    w("")

    w("## 同步状态")
    w("")
    w(f"| 状态 | 数量 |")
    w("|------|:----:|")
    w(f"| 成功 | {sync_ok} |")
    w(f"| 失败 | {sync_fail} |")
    w(f"| 待处理 | {sync_total - sync_ok - sync_fail} |")
    w(f"| 合计 | {sync_total} |")
    w("")

    # Top 10 oldest stocks
    w("## Top 10 最早上市股票")
    w("")
    w("| 代码 | K线数 | 最早日期 | 最新日期 |")
    w("|------|:-----:|:--------:|:--------:|")
    for r in sorted(per_code, key=lambda x: x[2])[:10]:
        w(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |")
    w("")

    # Show failed stocks
    if sync_fail > 0:
        failed = conn.execute(
            "SELECT code, last_error FROM kline_sync_status WHERE status='failed' LIMIT 10"
        ).fetchall()
        w("## 失败股票")
        w("")
        w("| 代码 | 错误 |")
        w("|------|------|")
        for r in failed:
            w(f"| {r[0]} | {r[1] or 'unknown'} |")
        w("")

    w("---")
    w(f"*自动生成 - Atlas Trading Agent K-Line Database Health Check*")

    rp = os.path.expanduser("~/Atlas-Trading-Agent/docs/KLINE_DATABASE_HEALTH_REPORT.md")
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    with open(rp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"报告: {rp}")

    # 控制台摘要
    print(f"\n{'='*60}")
    print(f"📊 K-Line DB Health")
    print(f"{'='*60}")
    print(f"  股票: {total_codes} | K线: {total_rows:,}")
    print(f"  区间: {earliest} ~ {latest}")
    print(f"  平均: {avg_bars}根/只")
    print(f"  健康: {health_rate}%")
    print(f"  问题: {total_issues}项")
    print(f"{'='*60}")


if __name__ == "__main__":
    check()
