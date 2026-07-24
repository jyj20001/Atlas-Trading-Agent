"""
Atlas Trading Agent — signal_database 模块测试

测试内容：
  1. 数据库自动建表
  2. 写入信号
  3. 查询信号
  4. 重复写入不报错
  5. 统计信息
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date
from data.signal_database import save_signals, query_signals, get_stats
from scanner.batch_runner import ScanSummary, ScanResult
from data.types import StockInfo, BreakoutSignal
from core.screener import ScreenerOutput

import logging
logging.disable(logging.CRITICAL)

P, F = 0, 0
def ok(label): global P; P+=1; print(f"  ✅ {label}")
def ng(label, e=""): global F; F+=1; print(f"  ❌ {label}  {e}")

print("=" * 60)
print("Signal Database 测试")
print("=" * 60)

# ── 构造模拟数据 ──
def _make_summary(score=105):
    s = ScanSummary()
    s.total = 100; s.skipped = 90; s.errors = 0
    s.start_time = 0.0; s.end_time = 30.0

    si = StockInfo("SZ.000977","000977","浪潮信息","SZSE")
    sig = BreakoutSignal("SZ.000977","浪潮信息",85.0,87.0,
                         ma200=66.0, above_ma200=True,
                         volume_ratio=1.5, turnover_pct=3.0,
                         change_5d_pct=5.0, consecutive_limit=0,
                         days_since_breakout=2,
                         score_trend=18, score_structure=22,
                         score_volume=18, score_turnover=12,
                         score_sector=8, score_risk=8,
                         total_score=86, suggestion="候选",
                         stop_loss=80.0, target=98.0, risk_reward=2.5)
    so = ScreenerOutput(True, signal=sig,
                         fundamental_score=8, fundamental_details="预增",
                         market_score=4, market_status="bull",
                         sector_score=8, sector_details="强",
                         breakout_stage="EARLY_BREAKOUT",
                         combined_score=score, recommendation="BUY_STOP")
    s.candidates.append(ScanResult(si, so, 2.0))
    return s

# ── 测试 1: 写入 ──
print("\n--- 1. 写入信号 ---")
summary = _make_summary(105)
n = save_signals(summary)
ok(f"写入 {n} 条") if n == 1 else ng(f"写入返回 {n}")

# ── 测试 2: 查询 ──
print("\n--- 2. 查询信号 ---")
today = date.today().isoformat()
rows = query_signals(scan_date=today)
ok(f"今日信号: {len(rows)} 条") if len(rows) >= 1 else ng(f"got {len(rows)}")
if rows:
    r = rows[0]
    ok(f"code={r['stock_code']}") if r["stock_code"] == "000977" else ng(f"code={r['stock_code']}")
    ok(f"combined={r['combined_score']}") if r["combined_score"] == 105 else ng(f"combined={r['combined_score']}")
    ok(f"buy_stop={r['buy_stop_price']}") if r["buy_stop_price"] == 87.0 else ng(f"buy_stop={r['buy_stop_price']}")
    ok(f"tech={r['technical_score']}") if r["technical_score"] == 86 else ng(f"tech={r['technical_score']}")

# ── 测试 3: 重复写入不报错 ──
print("\n--- 3. 重复写入 ---")
try:
    n2 = save_signals(_make_summary(105))
    ok(f"重复写入: {n2} 条") if n2 == 1 else ng(f"got {n2}")
except Exception as e:
    ng(f"重复写入异常: {e}")

# ── 测试 4: 多条写入 ──
print("\n--- 4. 多条写入 ---")
s3 = _make_summary(95)
si2 = StockInfo("SZ.600519","600519","贵州茅台","SSE")
sig2 = BreakoutSignal("SH.600519","贵州茅台",1500,1520,
                       ma200=1300, above_ma200=True,
                       volume_ratio=1.5, turnover_pct=1.0,
                       change_5d_pct=3.0, consecutive_limit=0,
                       days_since_breakout=1,
                       score_trend=18, score_structure=20,
                       score_volume=15, score_turnover=12,
                       score_sector=6, score_risk=8,
                       total_score=79, suggestion="候选",
                       stop_loss=1420, target=1700, risk_reward=2.0)
so2 = ScreenerOutput(True, signal=sig2,
                      fundamental_score=5,
                      market_score=4, market_status="bull",
                      sector_score=6,
                      breakout_stage="EARLY_BREAKOUT",
                      combined_score=95, recommendation="BUY_STOP")
s3.candidates.append(ScanResult(si2, so2, 1.5))
n3 = save_signals(s3)
ok(f"写入 {n3} 条") if n3 == 2 else ng(f"got {n3}")

# ── 测试 5: 统计 ──
print("\n--- 5. 统计 ---")
stats = get_stats()
ok(f"总计: {stats['total_signals']} 条") if stats["total_signals"] >= 2 else ng(f"total={stats['total_signals']}")
ok(f"日期数: {len(stats['scan_dates'])}") if len(stats["scan_dates"]) >= 1 else ng(f"dates={len(stats['scan_dates'])}")

# ── 测试 6: 按代码查询 ──
print("\n--- 6. 按代码查询 ---")
rows_977 = query_signals(stock_code="000977")
ok(f"000977: {len(rows_977)} 条") if len(rows_977) >= 1 else ng(f"got {len(rows_977)}")

# ── 结果 ──
print(f"\n{'='*60}")
print(f"📊 {P}/{P+F} 通过, {F} 失败")
print(f"{'='*60}")

# ── 清理测试数据 ──
from data.signal_database import _get_conn
conn = _get_conn()
conn.execute("DELETE FROM signals WHERE scan_date = ?", (date.today().isoformat(),))
conn.commit()
conn.close()
print("测试数据已清理")

sys.exit(0 if F == 0 else 1)
