"""
R002 Sector Relative Threshold — 分析脚本

研究问题：创业板/科创板 5日涨幅 50% 阈值是否存在误杀？

方法：
  1. 从 research/data/market_snapshot.db 只读快照加载 K 线数据
  2. 按板块分组：主板(600/000/001/002) vs 双创(300/688)
  3. 对每只股票每日计算 5 日涨幅
  4. 标记被当前规则（5日涨幅 > 50%）排除的日期
  5. 跟踪排除日后 20 个交易日的价格走势
  6. 按"误杀定义"统计误杀率
  7. 双样本 t 检验比较两组
  8. 输出 CSV 报告
"""

import csv
import math
import os
import sqlite3
from datetime import datetime
from pathlib import Path

# ── 只读快照路径（禁止直连生产库） ──
SNAPSHOT_PATH = Path(__file__).parent / "data" / "market_snapshot.db"
OUTPUT_DIR = Path(__file__).parent / "data"

# ── 板块分类 ──
BOARD_MAINLAND = ("600", "000", "001", "002")       # 主板
BOARD_GEM = ("300", "688")                           # 双创（创业板+科创板）


def classify_board(code: str) -> str:
    if code.startswith(BOARD_GEM):
        return "gem"  # 双创
    elif code.startswith(BOARD_MAINLAND):
        return "mainland"  # 主板
    return "other"


def run():
    print("=" * 60)
    print("R002 — 板块相对阈值研究")
    print("=" * 60)

    if not SNAPSHOT_PATH.exists():
        print(f"❌ 快照不存在: {SNAPSHOT_PATH}")
        print("   请先复制市场数据库快照")
        print("   cp [production_db_path] research/data/market_snapshot.db")
        return

    conn = sqlite3.connect(str(SNAPSHOT_PATH))
    conn.execute("PRAGMA query_only = ON")  # 只读模式

    # ── 获取所有股票代码和名称 ──
    codes = conn.execute(
        "SELECT DISTINCT code FROM daily_klines ORDER BY code"
    ).fetchall()
    codes = [r[0] for r in codes]

    print(f"\n全市场股票: {len(codes)} 只")
    mainland_codes = [c for c in codes if classify_board(c) == "mainland"]
    gem_codes = [c for c in codes if classify_board(c) == "gem"]
    print(f"  主板: {len(mainland_codes)} 只")
    print(f"  双创: {len(gem_codes)} 只")

    # ── 逐年分析 ──
    years = [2023, 2024, 2025]
    all_exclusions = []  # 所有被排除的记录，格式: (year, board, code, exclude_date, close, future_high_10d, future_high_20d)

    for year in years:
        print(f"\n--- {year}年分析 ---")

        # 获取该年有数据的所有股票
        year_stocks = conn.execute(
            "SELECT DISTINCT code FROM daily_klines "
            "WHERE trade_date LIKE ?",
            (f"{year}%",)
        ).fetchall()
        year_stocks = [r[0] for r in year_stocks]

        # 对每只股票检查 5 日涨幅
        for idx, code in enumerate(year_stocks):
            board = classify_board(code)
            if board == "other":
                continue

            # 获取该年所有K线（按日期排序）
            rows = conn.execute(
                "SELECT trade_date, close FROM daily_klines "
                "WHERE code = ? AND trade_date LIKE ? "
                "ORDER BY trade_date",
                (code, f"{year}%")
            ).fetchall()

            if len(rows) < 10:
                continue

            dates = [r[0] for r in rows]
            closes = [r[1] for r in rows]

            # 计算5日涨幅
            for i in range(5, len(rows)):
                chg_5d = (closes[i] - closes[i - 5]) / closes[i - 5] * 100

                if chg_5d > 50:
                    exclude_date = dates[i]
                    exclude_close = closes[i]

                    # 计算排除后10个交易日和20个交易日的最高涨幅
                    future_high_10d = None
                    future_high_20d = None

                    # 10个交易日
                    if i + 10 < len(closes):
                        future_high_10d = max(closes[i+1:i+11])
                    elif i + 1 < len(closes):
                        future_high_10d = max(closes[i+1:])

                    # 20个交易日
                    if i + 20 < len(closes):
                        future_high_20d = max(closes[i+1:i+21])
                    elif i + 1 < len(closes):
                        future_high_20d = max(closes[i+1:])

                    if future_high_10d is not None and future_high_20d is not None:
                        pct_10d = (future_high_10d - exclude_close) / exclude_close * 100
                        pct_20d = (future_high_20d - exclude_close) / exclude_close * 100

                        # 判断是否为误杀
                        false_positive_10d = pct_10d > 5
                        false_positive_20d = pct_20d > 10
                        false_positive = false_positive_10d or false_positive_20d

                        all_exclusions.append({
                            "year": year,
                            "board": board,
                            "code": code,
                            "exclude_date": exclude_date,
                            "close": exclude_close,
                            "chg_5d": round(chg_5d, 2),
                            "future_high_10d_pct": round(pct_10d, 2),
                            "future_high_20d_pct": round(pct_20d, 2),
                            "false_positive": false_positive,
                        })

            if (idx + 1) % 500 == 0:
                print(f"   进度: {idx+1}/{len(year_stocks)} 只, "
                      f"已发现 {sum(1 for e in all_exclusions if e['year']==year)} 次排除")

    conn.close()

    # ── 统计分析 ──
    print(f"\n{'='*60}")
    print("📊 分析结果")
    print(f"{'='*60}")

    print(f"\n总排除次数: {len(all_exclusions)}")

    for year in years:
        year_data = [e for e in all_exclusions if e["year"] == year]
        mainland_data = [e for e in year_data if e["board"] == "mainland"]
        gem_data = [e for e in year_data if e["board"] == "gem"]

        mainland_fp = sum(1 for e in mainland_data if e["false_positive"])
        gem_fp = sum(1 for e in gem_data if e["false_positive"])

        mainland_rate = mainland_fp / len(mainland_data) * 100 if mainland_data else 0
        gem_rate = gem_fp / len(gem_data) * 100 if gem_data else 0

        print(f"\n  {year}年:")
        print(f"    主板: {len(mainland_data)}次排除, "
              f"误杀率 {mainland_rate:.1f}%")
        print(f"    双创: {len(gem_data)}次排除, "
              f"误杀率 {gem_rate:.1f}%")

    # ── 总体统计 ──
    mainland_all = [e for e in all_exclusions if e["board"] == "mainland"]
    gem_all = [e for e in all_exclusions if e["board"] == "gem"]

    mainland_fp_all = sum(1 for e in mainland_all if e["false_positive"])
    gem_fp_all = sum(1 for e in gem_all if e["false_positive"])

    print(f"\n  总体:")
    print(f"    主板: {len(mainland_all)}次排除, "
          f"误杀率 {mainland_fp_all/len(mainland_all)*100 if mainland_all else 0:.1f}%")
    print(f"    双创: {len(gem_all)}次排除, "
          f"误杀率 {gem_fp_all/len(gem_all)*100 if gem_all else 0:.1f}%")

    # ── t 检验（简化版：Z 检验近似） ──
    if len(mainland_all) >= 30 and len(gem_all) >= 30:
        p1 = mainland_fp_all / len(mainland_all)
        p2 = gem_fp_all / len(gem_all)

        # 双比例 Z 检验
        p_pool = (mainland_fp_all + gem_fp_all) / (len(mainland_all) + len(gem_all))
        se = math.sqrt(p_pool * (1 - p_pool) * (1/len(mainland_all) + 1/len(gem_all)))
        z = (p2 - p1) / se if se > 0 else 0

        # 近似 p 值（Z分布）
        from scipy import stats as scipy_stats
        p_value = 2 * (1 - scipy_stats.norm.cdf(abs(z)))

        print(f"\n  双比例 Z 检验:")
        print(f"    Z 值: {z:.3f}")
        print(f"    p 值: {p_value:.4f}")
        print(f"    主板误杀率: {p1*100:.1f}%")
        print(f"    双创误杀率: {p2*100:.1f}%")
        if p_value < 0.05:
            print(f"    → 差异显著 (p < 0.05)")
        else:
            print(f"    → 差异不显著 (p >= 0.05)")
    else:
        print(f"\n  样本不足，无法进行 t 检验")
        print(f"    主板: {len(mainland_all)}次 ({mainland_fp_all}误杀)")
        print(f"    双创: {len(gem_all)}次 ({gem_fp_all}误杀)")

    # ── 导出 CSV ──
    csv_path = OUTPUT_DIR / "R002_exclusions.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "year", "board", "code", "exclude_date", "close",
            "chg_5d", "future_high_10d_pct", "future_high_20d_pct",
            "false_positive"
        ])
        writer.writeheader()
        writer.writerows(all_exclusions)

    print(f"\nCSV 已导出: {csv_path}")
    print(f"  共 {len(all_exclusions)} 条记录")

    # ── 更新 R002 文档的 Result 字段（标记） ──
    print(f"\n✅ R002 分析完成")
    print(f"   注意：2023-2024年数据覆盖有限（仅425只），")
    print(f"   结论需谨慎参考。建议补充完整 2023-2024 数据后再做最终判定。")


if __name__ == "__main__":
    run()
