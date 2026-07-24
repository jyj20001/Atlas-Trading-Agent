"""
Buy Stop V3 — 扫描报告生成

将 ScanSummary 输出为：
  1. Markdown 报告（output/reports/YYYYMMDD.md）
  2. JSON 数据（output/json/YYYYMMDD.json）
  3. CSV 信号历史（output/signal_history.csv，每日追加）
"""

import csv
import json
from datetime import date
from pathlib import Path
from typing import Optional

from config.settings import PROJECT_ROOT
from scanner.batch_runner import ScanSummary, ScanResult


OUTPUT_ROOT = PROJECT_ROOT / "output"
JSON_DIR = OUTPUT_ROOT / "json"
REPORT_DIR = OUTPUT_ROOT / "reports"
CSV_PATH = OUTPUT_ROOT / "signal_history.csv"
CSV_HEADERS = [
    "date", "symbol", "code", "name",
    "combined_score", "recommendation", "breakout_stage",
    "price", "buy_stop_price", "stop_loss", "target",
    "volume_ratio", "change_5d",
    "market_score", "market_status",
    "sector_score", "fundamental_score",
]


def ensure_dirs():
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def save_json(summary: ScanSummary, filename: Optional[str] = None) -> str:
    """保存JSON扫描数据"""
    ensure_dirs()
    if not filename:
        filename = date.today().strftime("%Y%m%d") + ".json"
    path = JSON_DIR / filename

    data = {
        "scan_date": date.today().isoformat(),
        "total": summary.total,
        "candidates_count": len(summary.candidates),
        "skipped_count": summary.skipped,
        "errors_count": summary.errors,
        "elapsed_sec": round(summary.elapsed, 2),
        "candidates": [r.to_dict() for r in summary.candidates],
        "top20": [r.to_dict() for r in summary.top(20)],
    }

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return str(path)


def save_report(summary: ScanSummary, filename: Optional[str] = None) -> str:
    """生成Markdown报告"""
    ensure_dirs()
    if not filename:
        filename = date.today().strftime("%Y%m%d") + ".md"
    path = REPORT_DIR / filename

    lines = []
    _w = lambda s="": lines.append(s)

    _w(f"# Buy Stop Scanner Report")
    _w(f"")
    _w(f"**日期:** {date.today().isoformat()}")
    _w(f"**扫描股票:** {summary.total} 只")
    _w(f"**候选:** {len(summary.candidates)} 只")
    _w(f"**跳过:** {summary.skipped} 只")
    _w(f"**错误:** {summary.errors} 只")
    _w(f"**耗时:** {summary.elapsed:.1f} 秒")
    _w(f"")
    _w(f"---")
    _w(f"")

    top = summary.top(20)
    if not top:
        _w("## 今日无符合Buy Stop条件股票")
        _w("")
        _w("没有股票通过全部筛选条件。")

    for rank, result in enumerate(top, 1):
        o = result.output
        s = o.signal if o else None
        stock = result.stock

        _w(f"## {rank}. {stock.name} ({stock.code})")
        _w(f"")
        _w(f"| 指标 | 值 |")
        _w(f"|------|-----|")

        if s:
            _w(f"| 当前价 | {s.price} |")
            _w(f"| 综合评分 | **{o.combined_score}/130** |")
            _w(f"| 推荐 | {o.recommendation} |")
            _w(f"| 突破阶段 | {o.breakout_stage} |")
            _w(f"")
            _w(f"### 评分明细")
            _w(f"")
            _w(f"| 维度 | 分数 |")
            _w(f"|------|:----:|")
            _w(f"| Technical | {s.total_score}/100 |")
            _w(f"| Fundamental | {o.fundamental_score}/15 |")
            _w(f"| Market | {o.market_score}/5 ({o.market_status}) |")
            _w(f"| Sector | {o.sector_score}/10 |")
            _w(f"")
            _w(f"### 交易参考")
            _w(f"")
            _w(f"| 指标 | 值 |")
            _w(f"|------|-----|")
            _w(f"| Buy Stop价格 | {s.breakout_price} |")
            _w(f"| 止损 | {s.stop_loss} |")
            _w(f"| 目标 | {s.target} |")
            _w(f"| 风险收益比 | {s.risk_reward} |")
            _w(f"| 量比 | {s.volume_ratio:.2f}x |")
            _w(f"| 5日涨幅 | {s.change_5d_pct:+.2f}% |")
            _w(f"")

        if o.risk_flags:
            _w(f"### ⚠️ 风险提示")
            for flag in o.risk_flags:
                _w(f"- {flag}")
            _w(f"")

        if o.fundamental_details and o.fundamental_details != "无近期基本面信号":
            _w(f"### 基本面")
            _w(f"- {o.fundamental_details}")
            _w(f"")

        if o.sector_details:
            _w(f"### 板块")
            _w(f"- {o.sector_details}")
            _w(f"")

        _w(f"---")
        _w(f"")

    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def save_signal_history(summary: ScanSummary) -> str:
    """
    将当日候选追加到 CSV 历史记录。
    文件不存在时自动写入表头。
    """
    ensure_dirs()
    today = date.today().isoformat()
    is_new = not CSV_PATH.exists()

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(CSV_HEADERS)

        for result in summary.candidates:
            o = result.output
            s = o.signal if o else None
            row = [
                today,
                result.stock.symbol,
                result.stock.code,
                result.stock.name,
                o.combined_score,
                o.recommendation,
                o.breakout_stage,
                s.price if s else "",
                s.breakout_price if s else "",
                s.stop_loss if s else "",
                s.target if s else "",
                s.volume_ratio if s else "",
                s.change_5d_pct if s else "",
                o.market_score,
                o.market_status,
                o.sector_score,
                o.fundamental_score,
            ]
            writer.writerow(row)

    return str(CSV_PATH)
