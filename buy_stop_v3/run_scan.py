"""
Buy Stop V3 — 全市场A股扫描入口（生产版）

- 无人值守运行：所有异常捕获，不中断
- 输出JSON+Markdown报告
- 企业微信推送（如有配置）
- 退出码：0=成功，1=有候选，2=异常

用法:
  python run_scan.py                     # 默认扫描100只
  python run_scan.py --stocks 500        # 扫描500只
  python run_scan.py --stocks 0          # 全市场(约20分钟)
  python run_scan.py --market HS300      # 沪深300
  python run_scan.py --stocks 0 --fundamental  # 全市场+基本面（慢）
"""

import argparse
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import logger
from scanner.universe import build_stock_pool
from scanner.batch_runner import BatchRunner
from scanner.report import save_json, save_report, save_signal_history
from utils.notifier import notify_scan
from data.signal_database import save_signals


def parse_args():
    parser = argparse.ArgumentParser(
        description="Buy Stop V3 — 全市场A股扫描"
    )
    parser.add_argument("--stocks", type=int, default=100,
                        help="扫描数量（0=全市场）")
    parser.add_argument("--market", type=str, default="A",
                        choices=["A", "HS300"],
                        help="股票池类型")
    parser.add_argument("--fundamental", action="store_true", default=False,
                        help="启用基本面评分")
    parser.add_argument("--no-fundamental", action="store_true", default=False,
                        help="关闭基本面评分")
    return parser.parse_args()


def main():
    exit_code = 0

    try:
        args = parse_args()
        enable_fund = args.fundamental and not args.no_fundamental

        logger.info(f"{'='*50}")
        logger.info(f"Buy Stop V3 扫描启动")
        logger.info(f"  市场: {args.market}")
        logger.info(f"  数量: {'全市场' if args.stocks == 0 else args.stocks}")
        logger.info(f"  基本面: {'启用' if enable_fund else '关闭'}")
        logger.info(f"{'='*50}")

        t_start = time.time()

        # 1. 构建股票池
        try:
            stocks = build_stock_pool(market=args.market)
        except Exception as e:
            logger.error(f"构建股票池失败: {e}")
            sys.exit(2)

        if args.stocks > 0:
            logger.info(f"限制扫描前 {args.stocks} 只")
            stocks = stocks[:args.stocks]

        # 2. 批量扫描
        runner = BatchRunner(enable_fundamental=enable_fund)
        summary = runner.run(stocks)

        # 3. 基本面数据源检查（结果后，用于推送提示）
        try:
            from data.snapshot_schema import get_table_count
            ann_count = get_table_count("announcement_snapshot")
            if ann_count < 50:
                warn = ("⚠️ 当前基本面数据暂未回填完整，扫描为纯技术面（115分制），"
                        "fundamental维度=0，不代表个股基本面无亮点")
                logger.warning(warn)
                summary.data_source_warning = warn
        except Exception as e:
            logger.debug(f"基本面数据检查跳过: {e}")

        # 4. 输出结果
        logger.info(f"\n{'='*50}")
        logger.info(f"扫描结果")
        logger.info(f"{'='*50}")
        logger.info(f"  总扫描: {summary.total} 只")
        logger.info(f"  候选: {len(summary.candidates)} 只")
        logger.info(f"  跳过(预过滤): {summary.skipped} 只")
        logger.info(f"  错误: {summary.errors} 只")
        logger.info(f"  耗时: {summary.elapsed:.1f} 秒")
        logger.info(f"  平均: {summary.elapsed/max(summary.total,1):.3f} 秒/只")

        if summary.candidates:
            logger.info(f"\n  TOP 5 候选:")
            for i, r in enumerate(summary.top(5), 1):
                o = r.output
                s = o.signal if o else None
                logger.info(f"  {i}. {r.stock.name}({r.stock.code}) "
                           f"评分={o.combined_score} "
                           f"阶段={o.breakout_stage} "
                           f"推荐={o.recommendation} "
                           f"价={s.price if s else '?'}")

        # 4. 保存报告（无论有无候选）
        try:
            json_path = save_json(summary)
            md_path = save_report(summary)
            csv_path = save_signal_history(summary)
            logger.info(f"\n  JSON: {json_path}")
            logger.info(f"  报告: {md_path}")
            if summary.candidates:
                logger.info(f"  历史CSV: {csv_path}")

            # 写入信号数据库（仅当有候选时）
            saved = save_signals(summary)
            if saved:
                logger.info(f"  信号DB: {saved} 条")
        except Exception as e:
            logger.error(f"保存报告失败: {e}")

        # 5. 企业微信推送（如有配置）
        try:
            notify_scan(summary)
        except Exception as e:
            logger.debug(f"企业微信推送失败: {e}")

        t_elapsed = time.time() - t_start
        logger.info(f"\n总计耗时: {t_elapsed:.1f} 秒")
        logger.info("Buy Stop V3 扫描完成")

        if summary.errors > 0:
            exit_code = 2
        elif len(summary.candidates) > 0:
            exit_code = 1  # 有候选
        else:
            exit_code = 0  # 正常无候选

    except Exception as e:
        logger.error(f"扫描主流程异常: {e}")
        traceback.print_exc()
        exit_code = 2

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
